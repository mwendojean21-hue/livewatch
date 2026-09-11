import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, Tooltip } from 'recharts'

const PALETTE = ['#4C5FFF', '#FF3B4E', '#22C08C', '#F5A623', '#8B93A7']

export function CategoryDonut({ data }: { data: { category: string; count: number }[] }) {
  const total = data.reduce((s, d) => s + d.count, 0)
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="relative h-40 w-40 shrink-0">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data} dataKey="count" nameKey="category" innerRadius={48} outerRadius={68} paddingAngle={2} stroke="none">
              {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display tabular-nums text-xl font-semibold">{total}</span>
          <span className="text-[11px] text-ink-muted">chaînes actives</span>
        </div>
      </div>
      <ul className="w-full space-y-2">
        {data.map((d, i) => (
          <li key={d.category} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
              {d.category}
            </span>
            <span className="tabular-nums font-medium">{total ? Math.round((d.count / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ViewersTrendChart({ data }: { data: { label: string; viewers: number }[] }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <BarChart data={data} barCategoryGap="28%">
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fill: 'var(--color-ink-muted)', fontSize: 12 }}
          />
          <Tooltip
            cursor={{ fill: 'var(--color-surface-2)' }}
            contentStyle={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              fontSize: 12,
            }}
            formatter={(v) => [`${Number(v).toLocaleString('fr-FR')} spectateurs`, '']}
            labelFormatter={() => ''}
          />
          <Bar dataKey="viewers" radius={[8, 8, 0, 0]} fill="var(--color-accent-2)" maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
