import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getBudget, getCategories, setBudget } from '../api'
import { fmtIDR } from '../utils'
import { useState } from 'react'

export default function Budget() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['budget'], queryFn: getBudget })
  const { data: cats } = useQuery({ queryKey: ['categories'], queryFn: getCategories })
  const rows: any[] = data?.data ?? []
  const categories: any[] = (cats?.data ?? []).filter((c: any) => !c.is_income)

  const [form, setForm] = useState({ category_id: '', amount: '' })
  const mutation = useMutation({
    mutationFn: () => setBudget(Number(form.category_id), Number(form.amount.replace(/\D/g, ''))),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['budget'] }); setForm({ category_id: '', amount: '' }) },
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Budget Bulan Ini</h1>

      {/* Set budget form */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
        <p className="text-sm font-semibold text-gray-300 mb-4">Set Budget Kategori</p>
        <div className="flex gap-3">
          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 flex-1"
            value={form.category_id}
            onChange={e => setForm(f => ({ ...f, category_id: e.target.value }))}
          >
            <option value="">Pilih kategori...</option>
            {categories.map((c: any) => (
              <option key={c.id} value={c.id}>{c.emoji} {c.name}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Nominal (contoh: 500000)"
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 w-48"
            value={form.amount}
            onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
          />
          <button
            onClick={() => mutation.mutate()}
            disabled={!form.category_id || !form.amount}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            Simpan
          </button>
        </div>
      </div>

      {/* Budget progress */}
      <div className="space-y-4">
        {rows.map((r: any) => {
          const pct = r.budget > 0 ? Math.min((r.spent / r.budget) * 100, 100) : 0
          const over = r.spent > r.budget
          return (
            <div key={r.name} className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
              <div className="flex justify-between items-center mb-3">
                <span className="font-medium">{r.emoji} {r.name}</span>
                <span className={`text-sm font-semibold ${over ? 'text-red-400' : 'text-gray-300'}`}>
                  {fmtIDR(r.spent)} / {fmtIDR(r.budget)}
                </span>
              </div>
              <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${over ? 'bg-red-500' : pct >= 75 ? 'bg-yellow-500' : 'bg-indigo-500'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="flex justify-between mt-1.5 text-xs text-gray-500">
                <span>{pct.toFixed(0)}% terpakai</span>
                <span>{over ? `🔴 Melebihi ${fmtIDR(r.spent - r.budget)}` : `Sisa ${fmtIDR(r.budget - r.spent)}`}</span>
              </div>
            </div>
          )
        })}
        {rows.length === 0 && (
          <div className="bg-gray-900 rounded-2xl border border-gray-800 p-10 text-center text-gray-500 text-sm">
            Belum ada budget yang diset. Gunakan form di atas untuk mulai.
          </div>
        )}
      </div>
    </div>
  )
}
