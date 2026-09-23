import { useEffect, useRef } from 'react'

interface Props {
  /** URL brute de la source (ce que l'ancien code appelait `_url`). */
  directUrl?: string
  /** Referer/en-têtes personnalisés pour ce flux (JSON, ex: {"Referer":"..."})
   * — renvoyés par /api/play quand le backend sait qu'une source précise
   * les exige (voir ExternalStream.referer). Absent de l'ancien code
   * d'origine, qui n'avait pas ce mécanisme ; ajouté ici en gardant tout le
   * reste du script hérité inchangé. */
  proxyHeaders?: string
  /** Conservé pour compat avec les appelants existants — n'est plus utilisé
   * directement : le script hérité reconstruit lui-même son URL de proxy
   * (`/proxy/stream?url=...`) à partir de `directUrl`, exactement comme
   * l'ancien code le faisait (`_proxyUrl = '/proxy/stream?url='+encodeURIComponent(_url)`). */
  src?: string
  type?: string
  poster?: string
  title: string
}

const HLS_JS_CDN = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js'
const DASH_JS_CDN = 'https://cdn.jsdelivr.net/npm/dashjs@4.7.4/dist/dash.all.min.js'

function loadScriptOnce(src: string, globalCheck: () => boolean): Promise<void> {
  if (globalCheck()) return Promise.resolve()
  const existing = document.querySelector(`script[data-lw-src="${src}"]`)
  if (existing) {
    return new Promise((resolve) => {
      if (globalCheck()) resolve()
      else existing.addEventListener('load', () => resolve(), { once: true })
    })
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.setAttribute('data-lw-src', src)
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(`Impossible de charger ${src}`))
    document.head.appendChild(script)
  })
}

/**
 * Ce composant fait tourner le code du lecteur IPTV/externe DE L'ANCIENNE
 * VERSION quasiment mot pour mot (extrait de Livewatch.py, la partie
 * <script> des pages /watch/iptv/{id} et /watch/external/{id}), plutôt
 * qu'une réécriture React. Après plusieurs passes de portage en TypeScript
 * qui n'ont pas résolu tous les cas réels malgré des tests de cohérence à
 * chaque étape, la source d'erreur la plus probable restante est la
 * traduction elle-même (une nuance perdue en cours de route) plutôt qu'un
 * bug de logique — faire tourner le JS original élimine ce risque.
 *
 * Seules deux choses ont été ajoutées au script original, aucune ne change
 * son comportement de lecture :
 *  1. `_url` est paramétré depuis les props React au lieu d'un template Jinja
 *     ({{ channel.url | tojson }} → JSON.stringify(directUrl) ici).
 *  2. `window.__wiCleanup` est exposé pour que React puisse détruire hls.js
 *     en quittant la page — l'ancien code ne s'appuyait que sur
 *     `beforeunload`, qui ne se déclenche jamais lors d'une navigation
 *     interne à une SPA (contrairement à un vrai rechargement de page).
 *     Sans ça, chaque changement de chaîne laisserait une instance hls.js
 *     tourner en arrière-plan.
 * Tout le reste — la chaîne de fallback à 5 niveaux, les réglages hls.js,
 * la détection de type, les messages d'erreur — est inchangé.
 */
export function VideoPlayer({ src, directUrl, proxyHeaders, type = 'hls', poster, title }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false

    // youtube / iframe restent gérés côté React (ce sont des <iframe>
    // simples, pas de lecteur média à initialiser).
    if (type === 'youtube' || type === 'iframe') return

    // Repartir d'un état propre en changeant de chaîne : le script hérité
    // suppose une page fraîchement chargée (une nouvelle page par chaîne
    // dans l'ancienne version) ; ici le même DOM est réutilisé d'une chaîne
    // à l'autre, donc un message d'erreur affiché pour la précédente doit
    // être masqué avant de retenter.
    const errEl = document.getElementById('wi-err')
    if (errEl) errEl.style.display = 'none'
    const videoEl = document.getElementById('wi-video') as HTMLVideoElement | null
    if (videoEl) videoEl.style.display = '' // au cas où _initAudio l'avait masqué pour la chaîne précédente

    async function boot() {
      try {
        await loadScriptOnce(HLS_JS_CDN, () => !!(window as any).Hls)
      } catch {
        // hls.js indisponible : le script hérité retombe sur la lecture
        // native (canPlayType) exactement comme dans l'ancienne version.
      }
      if (cancelled) return

      // dash.js n'est chargé qu'à la demande (évite d'alourdir le
      // chargement initial pour les chaînes qui n'en ont pas besoin), mais
      // AVANT de lancer le script si le type est déjà connu comme DASH.
      if (directUrl && /\.mpd(\?|$)/i.test(directUrl)) {
        try { await loadScriptOnce(DASH_JS_CDN, () => !!(window as any).dashjs) } catch { /* voir _initDASH */ }
      }
      if (cancelled) return

      const script = document.createElement('script')
      script.setAttribute('data-lw-player', '1')
      // Retirer le script précédent (changement de chaîne) pour ne pas les
      // accumuler dans le DOM — window.__wiCleanup() a déjà détruit son
      // instance hls.js au moment où l'effet précédent a été nettoyé.
      containerRef.current?.querySelectorAll('script[data-lw-player]').forEach((el) => el.remove())
      const proxyHeadersQs = proxyHeaders ? `&headers=${encodeURIComponent(proxyHeaders)}` : ''
      script.text = `
        (function(){
          var _url  = ${JSON.stringify(directUrl || '')};
          var _hls  = null;
          var _proxyUrl = _url ? '/proxy/stream?url='+encodeURIComponent(_url)+${JSON.stringify(proxyHeadersQs)} : '';

          function _detectType(url) {
            if (!url) return 'hls';
            var u = url.split('?')[0].toLowerCase();
            if (u.endsWith('.mp3') || u.endsWith('.aac') || u.endsWith('.flac')) return 'audio';
            if (u.endsWith('.mp4') || u.endsWith('.webm')) return 'mp4';
            if (u.endsWith('.mpd')) return 'dash';
            return 'hls';
          }
          var _type = _detectType(_url);

          function wiInit(){
            if (!_url) { _showErr('URL du flux manquante.'); return; }
            if (_type === 'audio') { _initAudio(); }
            else if (_type === 'mp4') { _initMP4Direct(); }
            else if (_type === 'dash') { _initDASH(); }
            else { _initHLSDirect(); }  // Direct en premier
          }

          function _initDASH(){
            var v = document.getElementById('wi-video');
            if (!v || !_url) { _showFinalErr(); return; }
            if (window.dashjs) {
              try {
                var dashPlayer = dashjs.MediaPlayer().create();
                dashPlayer.initialize(v, _url, true);
                dashPlayer.on(dashjs.MediaPlayer.events.ERROR, function(){ _showFinalErr(); });
              } catch (e) {
                _showFinalErr();
              }
            } else {
              _showFinalErr();
            }
          }

          function _initHLSDirect(){
            var v = document.getElementById('wi-video');
            if (!v) return;
            v.muted = true; // autoplay avec son bloqué silencieusement par les navigateurs
            if (window.Hls && Hls.isSupported()){
              if (_hls) { _hls.destroy(); _hls = null; }
              _hls = new Hls({
                enableWorker:true, lowLatencyMode:true,
                backBufferLength:30, maxBufferLength:90,
                manifestLoadingTimeOut:10000, manifestLoadingMaxRetry:1,
                levelLoadingTimeOut:10000, fragLoadingTimeOut:20000,
                renderTextTracksNatively: true,
                xhrSetup: function(xhr){ xhr.withCredentials=false; }
              });
              _hls.loadSource(_url);
              _hls.attachMedia(v);
              _hls.on(Hls.Events.MANIFEST_PARSED, function(){ v.play().catch(function(){}); });
              _hls.on(Hls.Events.ERROR, function(e,d){
                if(d.fatal){ _initHLSProxy(); }
              });
            } else if (v.canPlayType('application/vnd.apple.mpegurl')){
              v.src = _url; v.load(); v.play().catch(function(){ _initHLSProxy(); });
              v.addEventListener('error', function onE(){ v.removeEventListener('error',onE); _initHLSProxy(); }, {once:true});
            } else { _initMP4Direct(); }
          }

          function _initHLSProxy(){
            var v = document.getElementById('wi-video');
            if (!v || !_proxyUrl) { _initSafariProxy(); return; }
            v.muted = true;
            if (_hls) { _hls.destroy(); _hls = null; }
            if (window.Hls && Hls.isSupported()){
              _hls = new Hls({
                enableWorker:true, lowLatencyMode:false,
                manifestLoadingTimeOut:15000, manifestLoadingMaxRetry:2,
                levelLoadingTimeOut:15000, fragLoadingTimeOut:25000,
                renderTextTracksNatively: true
              });
              _hls.loadSource(_proxyUrl);
              _hls.attachMedia(v);
              _hls.on(Hls.Events.MANIFEST_PARSED, function(){ v.play().catch(function(){}); });
              _hls.on(Hls.Events.ERROR, function(e,d){
                if(d.fatal){ _initSafariProxy(); }
              });
            } else { _initSafariProxy(); }
          }

          function _initSafariProxy(){
            var v = document.getElementById('wi-video');
            if (!v) { _initMP4Direct(); return; }
            v.muted = true;
            if (v.canPlayType('application/vnd.apple.mpegurl')){
              v.src = _proxyUrl || _url; v.load();
              v.play().catch(function(){
                if(v.src !== _url){ v.src=_url; v.load(); v.play().catch(function(){ _initMP4Direct(); }); }
                else { _initMP4Direct(); }
              });
              v.addEventListener('error', function onE(){
                v.removeEventListener('error',onE);
                if(v.src !== _url){ v.src=_url; v.load(); } else { _initMP4Direct(); }
              }, {once:true});
            } else { _initMP4Direct(); }
          }

          function _initMP4Direct(){
            var v = document.getElementById('wi-video');
            if (!v || !_url) { _showFinalErr(); return; }
            if (_hls) { _hls.destroy(); _hls = null; }
            v.muted = true;
            v.src = _url; v.load(); v.play().catch(function(){});
            v.addEventListener('error', function(){ _showFinalErr(); }, {once:true});
          }

          function _initAudio(){
            var v = document.getElementById('wi-video');
            if (!v) return;
            var container = v.parentNode;
            var audio = document.createElement('audio');
            audio.id = 'wi-audio';
            audio.controls = true; audio.autoplay = true;
            audio.style.cssText = 'width:100%;max-width:400px;position:absolute;bottom:20px;left:50%;transform:translateX(-50%);';
            audio.innerHTML = '<source src="'+(_proxyUrl||_url)+'" type="audio/mpeg"><source src="'+_url+'">';
            v.style.display = 'none';
            container.appendChild(audio);
            audio.load();
            audio.addEventListener('error', function(){
              audio.src = _url; audio.load();
            });
          }

          function _showFinalErr(){ _showErr('Flux inaccessible. Il est peut-être hors ligne ou géo-bloqué.'); }
          function _showErr(msg){
            var el = document.getElementById('wi-err');
            var msgEl = document.getElementById('wi-err-msg');
            if (el) el.style.display = 'flex';
            if (msgEl) msgEl.textContent = msg;
          }

          window.__wiCleanup = function(){
            if (_hls) { try { _hls.destroy(); } catch(e){} _hls = null; }
            var audio = document.getElementById('wi-audio');
            if (audio && audio.parentNode) audio.parentNode.removeChild(audio);
          };

          wiInit();
        })();
      `
      containerRef.current?.appendChild(script)
    }

    boot()

    return () => {
      cancelled = true
      if ((window as any).__wiCleanup) {
        try { (window as any).__wiCleanup() } catch { /* ignoré */ }
        ;(window as any).__wiCleanup = null
      }
      // Le <script> injecté est un enfant du container, qui est démonté par
      // React de toute façon — pas besoin de le retirer manuellement.
    }
  }, [directUrl, proxyHeaders, type])

  if (type === 'youtube' || type === 'iframe') {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
        <iframe
          src={src}
          title={title}
          allow="autoplay; encrypted-media; picture-in-picture"
          allowFullScreen
          className="h-full w-full border-0"
        />
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black">
      <video
        id="wi-video"
        poster={poster}
        controls
        autoPlay
        muted
        playsInline
        className="h-full w-full"
      />
      <div
        id="wi-err"
        style={{ display: 'none' }}
        className="absolute inset-0 flex-col items-center justify-center gap-2 bg-black px-6 text-center text-white/80"
      >
        <span id="wi-err-msg" className="text-sm" />
      </div>
    </div>
  )
}
