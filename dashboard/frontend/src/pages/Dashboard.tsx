import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getSummary, getTimeseries } from '../api'
import { fmtIDR } from '../utils'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts'

const PERIODS = [
  { value: 'today', label: 'Hari Ini' },
  { value: 'week', label: 'Minggu Ini' },
  { value: 'month', label: 'Bulan Ini' },
]

const COLORS = ['#6366f1','#f59e0b','#10b981','#ef4444','#3b82f6','#ec4899','#8b5cf6','#14b8a6','#f97316','#a3e635']

export default function Dashboard() {
  const [period, setPeriod] = useState('month')
  const { data: summary } = useQuery({ queryKey: ['summary', period], queryFn: () => getSummary(period) })
  const { data: ts } = useQuery({ queryKey: ['timeseries'], queryFn: () => getTimeseries(30) })

  const rows: any[] = summary?.data ?? []
  const expenses = rows.filter(r => !r.is_income)
  const income = rows.filter(r => r.is_income)
  const totalExp = expenses.reduce((s: number, r: any) => s + r.total, 0)
  const totalInc = income.reduce((s: number, r: any) => s + r.total, 0)
  const net = totalInc - totalExp

  // Build time series chart data
  const tsRaw: any[] = ts?.data ?? []
  const tsMap: Record<string, { day: string; debit: number; credit: number }> = {}
  tsRaw.forEach(r => {
    if (!tsMap[r.day]) tsMap[r.day] = { day: r.day, debit: 0, credit: 0 }
    tsMap[r.day][r.type as 'debit' | 'credit'] += r.total
  })
  const tsData = Object.values(tsMap).sort((a, b) => a.day.localeCompare(b.day))

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="flex gap-2">
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                period === p.value ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
          <p className="text-sm text-gray-400">Total Pengeluaran</p>
          <p className="text-2xl font-bold text-red-400 mt-1">{fmtIDR(totalExp)}</p>
        </div>
        <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
          <p className="text-sm text-gray-400">Total Pemasukan</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{fmtIDR(totalInc)}</p>
        </div>
        <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
          <p className="text-sm text-gray-400">Selisih</p>
          <p className={`text-2xl font-bold mt-1 ${net >= 0 ? 'text-indigo-400' : 'text-red-400'}`}>{fmtIDR(net)}</p>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-6">
        {/* Area chart */}
        <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
          <p className="text-sm font-semibold text-gray-300 mb-4">Tren 30 Hari</p>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={tsData}>
              <defs>
                <linearGradient id="gDebit" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gCredit" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="day" tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => `${(v/1e6).toFixed(0)}jt`} />
              <Tooltip formatter={(v: number) => fmtIDR(v)} contentStyle={{ background: '#1f2937', border: 'none' }} />
              <Area type="monotone" dataKey="debit" stroke="#ef4444" fill="url(#gDebit)" name="Keluar" />
              <Area type="monotone" dataKey="credit" stroke="#10b981" fill="url(#gCredit)" name="Masuk" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Pie chart */}
        <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
          <p className="text-sm font-semibold text-gray-300 mb-4">Pengeluaran per Kategori</p>
          {expenses.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={expenses} dataKey="total" nameKey="category" cx="50%" cy="50%" outerRadius={70} label={({ category, percent }) => `${category} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                  {expenses.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => fmtIDR(v)} contentStyle={{ background: '#1f2937', border: 'none' }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-40 text-gray-500 text-sm">Belum ada data</div>
          )}
        </div>
      </div>

      {/* Category breakdown */}
      <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
        <p className="text-sm font-semibold text-gray-300 mb-4">Detail Pengeluaran</p>
        <div className="space-y-3">
          {expenses.map((r: any, i: number) => {
            const pct = totalExp > 0 ? (r.total / totalExp) * 100 : 0
            return (
              <div key={r.category} className="flex items-center gap-3">
                <span className="text-lg w-7">{r.emoji}</span>
                <div className="flex-1">
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-300">{r.category}</span>
                    <span className="text-gray-400">{fmtIDR(r.total)}</span>
                  </div>
                  <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: COLORS[i % COLORS.length] }} />
                  </div>
                </div>
              </div>
            )
          })}
          {expenses.length === 0 && <p className="text-gray-500 text-sm">Belum ada pengeluaran.</p>}
        </div>
      </div>
    </div>
  )
}
