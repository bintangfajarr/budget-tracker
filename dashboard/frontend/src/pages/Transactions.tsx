import { useQuery } from '@tanstack/react-query'
import { getTransactions } from '../api'
import { fmtIDR, fmtDate } from '../utils'

export default function Transactions() {
  const { data, isLoading } = useQuery({ queryKey: ['transactions'], queryFn: () => getTransactions(100) })
  const rows: any[] = data?.data ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Riwayat Transaksi</h1>

      {isLoading ? (
        <p className="text-gray-500">Memuat...</p>
      ) : (
        <div className="bg-gray-900 rounded-2xl border border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400">
                <th className="text-left px-5 py-3">Tanggal</th>
                <th className="text-left px-5 py-3">Keterangan</th>
                <th className="text-left px-5 py-3">Kategori</th>
                <th className="text-left px-5 py-3">Sumber</th>
                <th className="text-right px-5 py-3">Nominal</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r.id} className="border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors">
                  <td className="px-5 py-3 text-gray-400 whitespace-nowrap">{fmtDate(r.transaction_at)}</td>
                  <td className="px-5 py-3 text-gray-200 max-w-xs truncate">{r.description}</td>
                  <td className="px-5 py-3 text-gray-300">
                    {r.category_emoji} {r.category_name ?? '—'}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      r.source === 'email' ? 'bg-blue-900/50 text-blue-300' : 'bg-gray-700 text-gray-300'
                    }`}>
                      {r.source}
                    </span>
                  </td>
                  <td className={`px-5 py-3 text-right font-semibold ${
                    r.type === 'debit' ? 'text-red-400' : 'text-green-400'
                  }`}>
                    {r.type === 'debit' ? '-' : '+'}{fmtIDR(r.amount)}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-10 text-center text-gray-500">Belum ada transaksi</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
