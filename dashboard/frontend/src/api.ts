import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getSummary = (period: string) =>
  api.get('/summary', { params: { period } }).then(r => r.data)

export const getTransactions = (limit = 50) =>
  api.get('/transactions', { params: { limit } }).then(r => r.data)

export const getTimeseries = (days = 30) =>
  api.get('/transactions/timeseries', { params: { days } }).then(r => r.data)

export const getCategories = () =>
  api.get('/categories').then(r => r.data)

export const getBudget = () =>
  api.get('/budget').then(r => r.data)

export const setBudget = (category_id: number, amount: number) =>
  api.post('/budget', { category_id, amount })

export const createTransaction = (data: object) =>
  api.post('/transactions', data).then(r => r.data)

export const patchCategory = (tx_id: number, category_id: number) =>
  api.patch(`/transactions/${tx_id}/category`, { category_id })
