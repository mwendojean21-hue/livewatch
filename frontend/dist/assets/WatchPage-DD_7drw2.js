import{n as e}from"./categories-CHyf2PsF.js";import{r as t,t as n}from"./StreamCard-DYd9oecx.js";import{t as r}from"./flag-DFMes2aM.js";import{t as i}from"./heart-TBW9XM-A.js";import{C as a,E as o,b as s,g as c,i as l,n as u,o as d,r as f,s as p,t as m,v as h}from"./index-rXPBEp3I.js";var g={name:`send`,size:24,node:[[`path`,{d:`M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z`,key:`1ffxy3`}],[`path`,{d:`m21.854 2.147-10.94 10.939`,key:`12cjpa`}]]};g.node;var _=c(g),v=o(a(),1),y=h(),b=`https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js`,x=`https://cdn.jsdelivr.net/npm/dashjs@4.7.4/dist/dash.all.min.js`;function S(e,t){if(t())return Promise.resolve();let n=document.querySelector(`script[data-lw-src="${e}"]`);return n?new Promise(e=>{t()?e():n.addEventListener(`load`,()=>e(),{once:!0})}):new Promise((t,n)=>{let r=document.createElement(`script`);r.src=e,r.setAttribute(`data-lw-src`,e),r.onload=()=>t(),r.onerror=()=>n(Error(`Impossible de charger ${e}`)),document.head.appendChild(r)})}function C({src:e,directUrl:t,proxyHeaders:n,type:r=`hls`,poster:i,title:a}){let o=(0,v.useRef)(null);return(0,v.useEffect)(()=>{let e=!1;if(r===`youtube`||r===`iframe`)return;let i=document.getElementById(`wi-err`);i&&(i.style.display=`none`);let a=document.getElementById(`wi-video`);a&&(a.style.display=``);async function s(){try{await S(b,()=>!!window.Hls)}catch{}if(e)return;if(t&&/\.mpd(\?|$)/i.test(t))try{await S(x,()=>!!window.dashjs)}catch{}if(e)return;let r=document.createElement(`script`);r.setAttribute(`data-lw-player`,`1`),o.current?.querySelectorAll(`script[data-lw-player]`).forEach(e=>e.remove());let i=n?`&headers=${encodeURIComponent(n)}`:``;r.text=`
        (function(){
          var _url  = ${JSON.stringify(t||``)};
          var _hls  = null;
          var _proxyUrl = _url ? '/proxy/stream?url='+encodeURIComponent(_url)+${JSON.stringify(i)} : '';

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
      `,o.current?.appendChild(r)}return s(),()=>{if(e=!0,window.__wiCleanup){try{window.__wiCleanup()}catch{}window.__wiCleanup=null}}},[t,n,r]),r===`youtube`||r===`iframe`?(0,y.jsx)(`div`,{className:`aspect-video w-full overflow-hidden rounded-2xl bg-black`,children:(0,y.jsx)(`iframe`,{src:e,title:a,allow:`autoplay; encrypted-media; picture-in-picture`,allowFullScreen:!0,className:`h-full w-full border-0`})}):(0,y.jsxs)(`div`,{ref:o,className:`relative aspect-video w-full overflow-hidden rounded-2xl bg-black`,children:[(0,y.jsx)(`video`,{id:`wi-video`,poster:i,controls:!0,autoPlay:!0,muted:!0,playsInline:!0,className:`h-full w-full`}),(0,y.jsx)(`div`,{id:`wi-err`,style:{display:`none`},className:`absolute inset-0 flex-col items-center justify-center gap-2 bg-black px-6 text-center text-white/80`,children:(0,y.jsx)(`span`,{id:`wi-err-msg`,className:`text-sm`})})]})}function w(){let{kind:a,streamId:o}=s(),c=a??`external`,h=o??``,{data:g,loading:b}=d(()=>p.catalog(void 0,100),[]),x=g?.find(e=>e.id===h),{data:S,loading:w,error:T}=d(()=>p.resolvePlayback(c,h),[c,h]),{data:E}=d(()=>p.similarStreams(h),[h]),{data:D}=d(()=>p.comments(h),[h]),[O,k]=(0,v.useState)(!1),[A,j]=(0,v.useState)(null),[M,N]=(0,v.useState)(``);async function P(){k(e=>!e);try{let e=await p.likeStream(h);j(e.like_count)}catch{}}if(b||w)return(0,y.jsx)(`div`,{className:`mx-auto max-w-5xl`,children:(0,y.jsx)(l,{className:`aspect-video w-full`})});if(T||!S)return(0,y.jsxs)(`div`,{className:`mx-auto max-w-5xl card p-10 text-center text-ink-muted`,children:[`Impossible de lire cette chaîne`,T?` (${T})`:``,`.`]});let F=e(x?.category??`iptv`),I=x?.title??S.title??`Chaîne en direct`,L=S.stream_type===`youtube`?S.url:void 0;return(0,y.jsxs)(`div`,{className:`mx-auto max-w-5xl`,children:[(0,y.jsx)(m,{}),(0,y.jsx)(C,{src:L,directUrl:S.stream_type===`youtube`?void 0:S.url,proxyHeaders:S.headers??void 0,type:S.stream_type,title:I}),(0,y.jsxs)(`div`,{className:`mt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between`,children:[(0,y.jsxs)(`div`,{children:[(0,y.jsxs)(`div`,{className:`mb-1.5 flex items-center gap-2`,children:[(0,y.jsx)(u,{}),(0,y.jsx)(`span`,{className:`rounded-full px-2 py-0.5 text-xs font-medium ${F.chip} ${F.ink}`,children:F.name})]}),(0,y.jsx)(`h1`,{className:`font-display text-xl font-semibold sm:text-2xl`,children:I}),x&&(0,y.jsxs)(`p`,{className:`mt-1 flex items-center gap-1.5 text-sm text-ink-muted`,children:[(0,y.jsx)(t,{size:14}),` `,(x.viewers??0).toLocaleString(`fr-FR`),` spectateurs · `,x.country]})]}),(0,y.jsxs)(`div`,{className:`flex items-center gap-2`,children:[(0,y.jsxs)(`button`,{type:`button`,onClick:P,className:`flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${O?`border-accent bg-accent/10 text-accent`:`border-border text-ink-muted hover:text-ink`}`,children:[(0,y.jsx)(i,{size:15,fill:O?`currentColor`:`none`}),A??`J'aime`]}),(0,y.jsxs)(`button`,{type:`button`,onClick:()=>p.reportStream(h,`contenu inapproprié`).catch(()=>{}),className:`flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink`,children:[(0,y.jsx)(r,{size:15}),` Signaler`]})]})]}),(0,y.jsxs)(`div`,{className:`mt-8 grid gap-8 lg:grid-cols-[1fr_320px]`,children:[(0,y.jsxs)(`div`,{children:[(0,y.jsx)(f,{title:`Commentaires`}),(0,y.jsxs)(`form`,{onSubmit:e=>{e.preventDefault(),M.trim()&&(p.postComment(h,M).catch(()=>{}),N(``))},className:`mb-4 flex items-center gap-2`,children:[(0,y.jsx)(`input`,{value:M,onChange:e=>N(e.target.value),placeholder:`Ajouter un commentaire…`,className:`flex-1 rounded-full border border-border bg-surface px-4 py-2.5 text-sm outline-none focus-visible:border-accent-2`}),(0,y.jsx)(`button`,{type:`submit`,"aria-label":`Envoyer`,className:`flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-2 text-white`,children:(0,y.jsx)(_,{size:15})})]}),(0,y.jsx)(`div`,{className:`space-y-3`,children:D?.map(e=>(0,y.jsxs)(`div`,{className:`card p-3.5 text-sm`,children:[(0,y.jsx)(`p`,{children:e.content}),(0,y.jsx)(`p`,{className:`mt-1 text-xs text-ink-muted`,children:new Date(e.created_at).toLocaleTimeString(`fr-FR`,{hour:`2-digit`,minute:`2-digit`})})]},e.id))})]}),(0,y.jsxs)(`div`,{children:[(0,y.jsx)(f,{title:`Chaînes similaires`}),(0,y.jsx)(`div`,{className:`grid gap-3`,children:E&&E.length>0?E.map(e=>(0,y.jsx)(n,{stream:{...e,quality:``,logo:e.logo||``}},e.id)):E&&(0,y.jsx)(`p`,{className:`text-sm text-ink-muted`,children:`Aucune chaîne similaire pour l'instant.`})})]})]})]})}export{w as WatchPage};