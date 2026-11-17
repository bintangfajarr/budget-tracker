import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, ChevronRight, Plus, Trash2, Pencil, X,
  CalendarDays, LayoutGrid, Search,
} from 'lucide-react'
import {
  getCalendarMonth, getCalendarYear, getNotes,
  createNote, patchNote, deleteNote,
} from '../api'
import { fmtIDR } from '../utils'

type Mood = 'good' | 'ok' | 'bad' | ''

const MONTHS = [
  'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
  'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
]
const DOW = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min']

const MOOD_DOT: Record<string, string> = {
  good: 'bg-green-400',
  ok: 'bg-yellow-400',
  bad: 'bg-red-400',
}
const MOOD_LABEL: Record<string, string> = {
  good: '😀 Baik',
  ok: '😐 Biasa',
  bad: '😕 Buruk',
}

const todayISO = () => new Date().toISOString().slice(0, 10)

/** Monday-first offset for the 1st of a month. */
function leadingBlanks(year: number, month: number) {
  const jsDow = new Date(year, month - 1, 1).getDay() // 0=Sun
  return (jsDow + 6) % 7
}

export default function Calendar() {
  const qc = useQueryClient()
  const now = new Date()

  const [view, setView] = useState<'month' | 'year'>('month')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [selected, setSelected] = useState<string>(todayISO())
  const [search, setSearch] = useState('')

  // editor state
  const [open, setOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [fTitle, setFTitle] = useState('')
  const [fBody, setFBody] = useState('')
  const [fMood, setFMood] = useState<Mood>('')
  const [fTags, setFTags] = useState('')
  const [fDate, setFDate] = useState(todayISO())

  const monthQ = useQuery({
    queryKey: ['calendar', year, month],
    queryFn: () => getCalendarMonth(year, month),
    enabled: view === 'month',
  })
  const yearQ = useQuery({
    queryKey: ['calendar', year],
    queryFn: () => getCalendarYear(year),
    enabled: view === 'year',
  })
  const dayQ = useQuery({
    queryKey: ['notes', 'day', selected],
    queryFn: () => getNotes({ day: selected }),
    enabled: view === 'month' && !search,
  })
  const searchQ = useQuery({
    queryKey: ['notes', 'search', search],
    queryFn: () => getNotes({ q: search }),
    enabled: search.length > 1,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['calendar'] })
    qc.invalidateQueries({ queryKey: ['notes'] })
  }

  const createM = useMutation({ mutationFn: createNote, onSuccess: () => { invalidate(); closeEditor() } })
  const patchM = useMutation({
    mutationFn: (v: { id: number; data: object }) => patchNote(v.id, v.data),
    onSuccess: () => { invalidate(); closeEditor() },
  })
  const delM = useMutation({ mutationFn: deleteNote, onSuccess: invalidate })

  function openNew(day?: string) {
    setEditId(null)
    setFTitle(''); setFBody(''); setFMood(''); setFTags('')
    setFDate(day ?? selected)
    setOpen(true)
  }

  function openEdit(n: any) {
    setEditId(n.id)
    setFTitle(n.title ?? '')
    setFBody(n.body ?? '')
    setFMood((n.mood ?? '') as Mood)
    setFTags((n.tags ?? []).join(', '))
    setFDate(n.note_date)
    setOpen(true)
  }

  function closeEditor() {
    setOpen(false)
    setEditId(null)
  }

  function submit() {
    if (!fBody.trim()) return
    const tags = fTags.split(',').map(t => t.trim()).filter(Boolean)
    const payload = {
      note_date: fDate,
      title: fTitle.trim() || null,
      body: fBody.trim(),
      mood: fMood || null,
      tags,
    }
    if (editId) patchM.mutate({ id: editId, data: payload })
    else createM.mutate({ ...payload, source: 'web' })
  }

  const shiftMonth = (d: number) => {
    let m = month + d, y = year
    if (m < 1) { m = 12; y -= 1 }
    if (m > 12) { m = 1; y += 1 }
    setMonth(m); setYear(y)
  }

  const days: any[] = monthQ.data?.days ?? []
  const totals = (view === 'month' ? monthQ.data?.totals : yearQ.data?.totals) ?? {}
  const notes: any[] = search.length > 1 ? (searchQ.data?.data ?? []) : (dayQ.data?.data ?? [])

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Catatan</h1>
        <div className="flex-1" />

        <div className="flex rounded-lg overflow-hidden border border-gray-800">
          <button
            onClick={() => setView('month')}
            className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${
              view === 'month' ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-400 hover:text-white'
            }`}
          >
            <CalendarDays size={15} /> Bulan
          </button>
          <button
            onClick={() => setView('year')}
            className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${
              view === 'year' ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-400 hover:text-white'
            }`}
          >
            <LayoutGrid size={15} /> Tahun
          </button>
        </div>

        <button
          onClick={() => openNew()}
          className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium flex items-center gap-1.5"
        >
          <Plus size={16} /> Catatan Baru
        </button>
      </div>

      {/* summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total catatan" value={totals.notes ?? 0} />
        <Stat label="Hari ada catatan" value={totals.days_with_notes ?? 0} />
        <Stat label="Pengeluaran" value={fmtIDR(totals.spent ?? 0)} tone="text-red-400" />
        <Stat label="Pemasukan" value={fmtIDR(totals.received ?? 0)} tone="text-green-400" />
      </div>

      {view === 'month' ? (
        <div className="grid lg:grid-cols-[1fr_380px] gap-6">
          {/* calendar grid */}
          <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <button onClick={() => shiftMonth(-1)} className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400">
                <ChevronLeft size={18} />
              </button>
              <div className="font-semibold">{MONTHS[month - 1]} {year}</div>
              <button onClick={() => shiftMonth(1)} className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400">
                <ChevronRight size={18} />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-1 mb-1">
              {DOW.map(d => (
                <div key={d} className="text-center text-[11px] text-gray-500 font-medium py-1">{d}</div>
              ))}
            </div>

            {monthQ.isLoading ? (
              <p className="text-gray-500 text-sm py-8 text-center">Memuat...</p>
            ) : (
              <div className="grid grid-cols-7 gap-1">
                {Array.from({ length: leadingBlanks(year, month) }).map((_, i) => (
                  <div key={`b${i}`} />
                ))}
                {days.map(d => {
                  const isToday = d.date === todayISO()
                  const isSel = d.date === selected
                  const dayNum = Number(d.date.slice(-2))
                  return (
                    <button
                      key={d.date}
                      onClick={() => setSelected(d.date)}
                      onDoubleClick={() => openNew(d.date)}
                      className={`aspect-square rounded-lg p-1.5 flex flex-col items-start text-left transition-colors border ${
                        isSel
                          ? 'bg-indigo-600/25 border-indigo-500'
                          : isToday
                          ? 'bg-gray-800 border-gray-600'
                          : 'bg-gray-800/40 border-transparent hover:bg-gray-800'
                      }`}
                      title={d.first_title ?? undefined}
                    >
                      <span className={`text-xs font-medium ${isToday ? 'text-indigo-300' : 'text-gray-300'}`}>
                        {dayNum}
                      </span>

                      <div className="flex-1" />

                      <div className="flex items-center gap-0.5 flex-wrap">
                        {(d.moods ?? []).slice(0, 3).map((m: string, i: number) => (
                          <span key={i} className={`w-1.5 h-1.5 rounded-full ${MOOD_DOT[m] ?? 'bg-gray-500'}`} />
                        ))}
                        {d.note_count > 0 && (d.moods ?? []).length === 0 && (
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                        )}
                      </div>

                      {d.note_count > 1 && (
                        <span className="text-[9px] text-gray-500 leading-none">{d.note_count} catatan</span>
                      )}
                      {Number(d.spent) > 0 && (
                        <span className="text-[9px] text-red-400/80 leading-none truncate w-full">
                          -{(Number(d.spent) / 1000).toFixed(0)}k
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* side panel */}
          <div className="space-y-4">
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Cari catatan..."
                className="w-full bg-gray-900 border border-gray-800 rounded-lg pl-9 pr-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>

            <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-semibold text-sm">
                  {search.length > 1
                    ? `Hasil pencarian (${notes.length})`
                    : new Date(selected).toLocaleDateString('id-ID', {
                        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
                      })}
                </h2>
                {search.length > 1 && (
                  <button onClick={() => setSearch('')} className="text-gray-500 hover:text-white">
                    <X size={15} />
                  </button>
                )}
              </div>

              {notes.length === 0 ? (
                <div className="text-center py-7">
                  <p className="text-gray-500 text-sm mb-3">Belum ada catatan</p>
                  {search.length <= 1 && (
                    <button
                      onClick={() => openNew()}
                      className="text-indigo-400 hover:text-indigo-300 text-sm font-medium"
                    >
                      + Tambah catatan
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-2.5">
                  {notes.map(n => (
                    <div key={n.id} className="bg-gray-800/50 rounded-xl p-3 group">
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          {n.title && <div className="font-medium text-sm mb-0.5">{n.title}</div>}
                          <p className="text-sm text-gray-300 whitespace-pre-wrap break-words">{n.body}</p>

                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            {n.mood && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">
                                {MOOD_LABEL[n.mood]}
                              </span>
                            )}
                            {(n.tags ?? []).map((t: string) => (
                              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-900/40 text-indigo-300">
                                #{t}
                              </span>
                            ))}
                            <span className="text-[10px] text-gray-600">{n.source}</span>
                            {search.length > 1 && (
                              <span className="text-[10px] text-gray-500">{n.note_date}</span>
                            )}
                          </div>
                        </div>

                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => openEdit(n)} className="p-1 text-gray-500 hover:text-white">
                            <Pencil size={13} />
                          </button>
                          <button
                            onClick={() => { if (confirm('Hapus catatan ini?')) delM.mutate(n.id) }}
                            className="p-1 text-gray-500 hover:text-red-400"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* year view */
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
          <div className="flex items-center justify-between mb-5">
            <button onClick={() => setYear(year - 1)} className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400">
              <ChevronLeft size={18} />
            </button>
            <div className="font-semibold text-lg">{year}</div>
            <button onClick={() => setYear(year + 1)} className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400">
              <ChevronRight size={18} />
            </button>
          </div>

          {yearQ.isLoading ? (
            <p className="text-gray-500 text-sm py-8 text-center">Memuat...</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {(yearQ.data?.months ?? []).map((m: any) => {
                const intensity = Math.min(m.days_with_notes / 15, 1)
                return (
                  <button
                    key={m.month_num}
                    onClick={() => { setMonth(m.month_num); setView('month') }}
                    className="rounded-xl border border-gray-800 p-4 text-left hover:border-indigo-500 transition-colors"
                    style={{ background: `rgba(99,102,241,${0.06 + intensity * 0.22})` }}
                  >
                    <div className="font-medium text-sm mb-2">{MONTHS[m.month_num - 1]}</div>
                    <div className="text-xs text-gray-400 space-y-0.5">
                      <div>{m.note_count} catatan &middot; {m.days_with_notes} hari</div>
                      {Number(m.spent) > 0 && (
                        <div className="text-red-400/80">-{fmtIDR(Number(m.spent))}</div>
                      )}
                      {Number(m.received) > 0 && (
                        <div className="text-green-400/80">+{fmtIDR(Number(m.received))}</div>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* editor modal */}
      {open && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50"
          onClick={closeEditor}
        >
          <div
            className="bg-gray-900 rounded-2xl border border-gray-800 p-6 w-full max-w-lg space-y-4"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{editId ? 'Edit Catatan' : 'Catatan Baru'}</h2>
              <button onClick={closeEditor} className="text-gray-500 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Tanggal</label>
                <input
                  type="date"
                  value={fDate}
                  onChange={e => setFDate(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Judul (opsional)</label>
                <input
                  value={fTitle}
                  onChange={e => setFTitle(e.target.value)}
                  placeholder="Judul singkat"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Isi catatan</label>
                <textarea
                  value={fBody}
                  onChange={e => setFBody(e.target.value)}
                  rows={5}
                  placeholder="Tulis apa saja..."
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500 resize-none"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Mood</label>
                <div className="flex gap-2">
                  {([['', 'Tidak ada'], ['good', '😀 Baik'], ['ok', '😐 Biasa'], ['bad', '😕 Buruk']] as const).map(
                    ([v, label]) => (
                      <button
                        key={v}
                        onClick={() => setFMood(v as Mood)}
                        className={`px-2.5 py-1.5 rounded-lg text-xs border ${
                          fMood === v
                            ? 'bg-indigo-600 border-indigo-500 text-white'
                            : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white'
                        }`}
                      >
                        {label}
                      </button>
                    ),
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">Tag (pisahkan dengan koma)</label>
                <input
                  value={fTags}
                  onChange={e => setFTags(e.target.value)}
                  placeholder="kerja, pribadi, ide"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-1">
              <button
                onClick={submit}
                disabled={!fBody.trim() || createM.isPending || patchM.isPending}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg py-2 text-sm font-medium"
              >
                {createM.isPending || patchM.isPending ? 'Menyimpan...' : editId ? 'Simpan' : 'Tambah'}
              </button>
              <button
                onClick={closeEditor}
                className="px-4 bg-gray-800 hover:bg-gray-700 rounded-lg py-2 text-sm"
              >
                Batal
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: any; tone?: string }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
      <div className="text-[11px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-lg font-semibold mt-0.5 ${tone ?? ''}`}>{value}</div>
    </div>
  )
}
