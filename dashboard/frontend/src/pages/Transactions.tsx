import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, RefreshCw } from 'lucide-react'
import { getTransactions, deleteTransaction } from '../api'
import { fmtIDR, fmtDate } from '../utils'

export default function Transactions() {
  const qc = useQueryClient()
  const [busyId, setBusyId] = useState<number | null>(null)

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['transactions'],
    queryFn: () => getTransactions(100),
  })
  const rows: any[] = data?.data ?? []

  const delM = useMutation({
    mutationFn: deleteTransaction,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      qc.invalidateQueries({ queryKey: ['calendar'] })
      setBusyId(null)
    },
    onError: () => setBusyId(null),
  })

  function remove(r: any) {
    const label = `${r.type === 'debit' ? '-' : '+'}${fmtIDR(r.amount)} — ${r.description}`
    if (!confirm(`Hapus transaksi ini?\n\n${label}`)) return
    setBusyId(r.id)
    delM.mutate(r.id)
  }

  const totalDebit = rows.filter(r => r.type === 'debit').reduce((a, r) => a + Number(r.amount), 0)
  const totalCredit = rows.filter(r => r.type === 'credit').reduce((a, r) => a + Number(r.amount), 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Riwayat Transaksi</h1>
        <div className="flex-1" />
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-sm flex items-center gap-1.5"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          Muat ulang
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wide">Jumlah transaksi</div>
          <div className="text-lg font-semibold mt-0.5">{rows.length}</div>
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wide">Pengeluaran</div>
          <div className="text-lg font-semibold mt-0.5 text-red-400">{fmtIDR(totalDebit)}</div>
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wide">Pemasukan</div>
          <div className="text-lg font-semibold mt-0.5 text-green-400">{fmtIDR(totalCredit)}</div>
        </div>
      </div>

      {isLoading ? (
        <p className="text-gray-500">Memuat...</p>
      ) : (
        <div className="bg-gray-900 rounded-2xl border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[680px]">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400">
                <th className="text-left px-5 py-3">Tanggal</th>
                <th className="text-left px-5 py-3">Keterangan</th>
                <th className="text-left px-5 py-3">Kategori</th>
                <th className="text-left px-5 py-3">Sumber</th>
                <th className="text-right px-5 py-3">Nominal</th>
                <th className="px-3 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr
                  key={r.id}
                  className={`border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors group ${
                    busyId === r.id ? 'opacity-40' : ''
                  }`}
                >
                  <td className="px-5 py-3 text-gray-400 whitespace-nowrap">{fmtDate(r.transaction_at)}</td>
                  <td className="px-5 py-3 text-gray-200 max-w-xs truncate" title={r.description}>
                    {r.description}
                  </td>
                  <td className="px-5 py-3 text-gray-300 whitespace-nowrap">
                    {r.category_emoji} {r.category_name ?? '—'}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      r.source === 'email' ? 'bg-blue-900/50 text-blue-300' : 'bg-gray-700 text-gray-300'
                    }`}>
                      {r.source}
                    </span>
                  </td>
                  <td className={`px-5 py-3 text-right font-semibold whitespace-nowrap ${
                    r.type === 'debit' ? 'text-red-400' : 'text-green-400'
                  }`}>
                    {r.type === 'debit' ? '-' : '+'}{fmtIDR(r.amount)}
                  </td>
                  <td className="px-3 py-3">
                    <button
                      onClick={() => remove(r)}
                      disabled={busyId === r.id}
                      title="Hapus transaksi"
                      className="p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-500/10
                                 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity
                                 disabled:cursor-not-allowed"
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-gray-500">
                    Belum ada transaksi
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {delM.isError && (
        <p className="text-sm text-red-400">Gagal menghapus transaksi. Coba muat ulang halaman.</p>
      )}
    </div>
  )
}
