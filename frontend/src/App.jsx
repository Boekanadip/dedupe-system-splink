import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, BrainCircuit,
  CalendarDays, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  CircleAlert, Clock3, CloudUpload, Code2, Database, Download, FileSpreadsheet,
  FileText, Filter, Gauge, HardDrive, History, Layers3, LayoutDashboard,
  ListChecks, Menu, MoreHorizontal, Plus, Play, Search, Server, Settings,
  ShieldCheck, SlidersHorizontal, Sparkles, Table2, Workflow, X, Zap,
  AlertTriangle, CircleDot, Eye, ExternalLink, RefreshCw, Save, SearchX,
  CheckCheck, Terminal, PanelLeftClose, PanelLeftOpen, Sun, Moon, Copy,
} from 'lucide-react'
import * as dedupApi from './services/dedupApi'
import { getHealth, getStats, getPairs, getModelInfo, runDedup, reload, toReviewRow } from './services/dedupApi'

const navigation = [
  { group: 'WORKSPACE', items: [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    { id: 'sources', label: 'Data sources', icon: Database },
    { id: 'datasets', label: 'Datasets', icon: Table2 },
  ]},
  { group: 'OPERATIONS', items: [
    { id: 'processing', label: 'Processing', icon: Workflow },
    { id: 'review', label: 'Review queue', icon: ListChecks, count: '128' },
    { id: 'history', label: 'Run history', icon: History },
  ]},
  { group: 'INTELLIGENCE', items: [
    { id: 'models', label: 'Model registry', icon: BrainCircuit },
    { id: 'analytics', label: 'Evaluation', icon: Activity },
  ]},
  { group: 'ADMINISTRATION', items: [
    { id: 'database', label: 'Database', icon: Server },
    { id: 'settings', label: 'Settings', icon: Settings },
  ]},
]

const pageMeta = {
  dashboard: ['Overview', 'A clear view of your data operations and processing activity.'],
  sources: ['Data sources', 'Connect files and database tables to your workspace.'],
  datasets: ['Datasets', 'Explore imported data, schemas, and validation status.'],
  processing: ['Processing workspace', 'Configure a reusable pipeline and submit a processing run.'],
  review: ['Review queue', 'Resolve uncertain record pairs with a traceable human decision.'],
  history: ['Run history', 'Track processing runs, outcomes, and output destinations.'],
  models: ['Model registry', 'Manage processing engines independently from the platform UI.'],
  analytics: ['Evaluation', 'Monitor data quality, linkage outcomes, and model evaluation.'],
  database: ['Database management', 'Configure PostgreSQL connections and output destinations.'],
  settings: ['Workspace settings', 'Manage workspace preferences and operational defaults.'],
}

const initialDatasets = [
  { id: 'DS-0142', name: 'crm_customers_q4.csv', source: 'File upload', rows: '103,858', columns: 18, status: 'Validated', updated: 'Today, 08:42', size: '18.6 MB' },
  { id: 'DS-0141', name: 'customer_master', source: 'PostgreSQL', rows: '48,210', columns: 16, status: 'Validated', updated: 'Yesterday, 16:24', size: 'Database table' },
  { id: 'DS-0140', name: 'legacy_accounts.csv', source: 'File upload', rows: '21,504', columns: 12, status: 'Needs mapping', updated: 'Nov 18, 2026', size: '6.2 MB' },
  { id: 'DS-0139', name: 'crm_leads_staging', source: 'PostgreSQL', rows: '8,920', columns: 14, status: 'Validated', updated: 'Nov 17, 2026', size: 'Database table' },
  { id: 'DS-0138', name: 'customer_archive.csv', source: 'File upload', rows: '—', columns: 15, status: 'Draft', updated: 'Nov 16, 2026', size: '11.4 MB' },
]

const initialRuns = [
  { id: 'RUN-0268', dataset: 'crm_customers_q4.csv', engine: 'Splink CRM Linkage', status: 'Completed', records: '103,858', matched: '2,841', review: '1,284', started: 'Today, 08:42', duration: '04m 28s', output: 'di_results.run_0268' },
  { id: 'RUN-0267', dataset: 'customer_master', engine: 'Splink CRM Linkage', status: 'Completed', records: '48,210', matched: '1,120', review: '486', started: 'Yesterday, 16:24', duration: '02m 51s', output: 'di_results.run_0267' },
  { id: 'RUN-0266', dataset: 'legacy_accounts.csv', engine: 'Splink CRM Linkage', status: 'Needs review', records: '21,504', matched: '—', review: '—', started: 'Nov 18, 2026', duration: '—', output: 'Pending review' },
  { id: 'RUN-0265', dataset: 'crm_leads_staging', engine: 'Splink CRM Linkage', status: 'Failed', records: '8,920', matched: '—', review: '—', started: 'Nov 17, 2026', duration: '00m 18s', output: 'No output written' },
]

const reviewSeed = [
  { id: 'PAIR-88421', left: 'Rizky Pratama', right: 'Rizky P.', email: 'rizky.pratama@mail.com', rightEmail: 'rizky.p@mail.com', city: 'Bandung', rightCity: 'Bandung', phone: '+62 812-xxx-1092', rightPhone: '+62 812-xxx-1092', score: 0.84, decision: 'REVIEW', reason: 'Name similarity · Exact phone · Exact city' },
  { id: 'PAIR-88420', left: 'Siti Rahmawati', right: 'Siti Rachmawati', email: 'siti.r@mail.com', rightEmail: 'siti.rachmawati@mail.com', city: 'Jakarta', rightCity: 'Bekasi', phone: '+62 878-xxx-2104', rightPhone: '+62 878-xxx-2104', score: 0.77, decision: 'REVIEW', reason: 'Similar name · Exact phone · City conflict' },
  { id: 'PAIR-88418', left: 'Andi Saputra', right: 'Andi S.', email: 'andi.saputra@mail.com', rightEmail: 'andi.saputra@mail.com', city: 'Surabaya', rightCity: 'Surabaya', phone: '+62 813-xxx-4401', rightPhone: '+62 813-xxx-4401', score: 0.93, decision: 'REVIEW', reason: 'Exact email · Exact phone · Shortened name' },
  { id: 'PAIR-88412', left: 'Dewi Anggraini', right: 'Dewi A.', email: 'dewi.anggraini@mail.com', rightEmail: 'dewi.a@mail.com', city: 'Depok', rightCity: 'Depok', phone: '+62 821-xxx-7822', rightPhone: '+62 821-xxx-7822', score: 0.69, decision: 'REVIEW', reason: 'Phone prefix · Name similarity · Email local-part' },
]

const modelSeed = [
  { id: 'MDL-0001', name: 'Splink CRM Linkage', family: 'Probabilistic record linkage', version: 'Repository integration', runtime: 'Python · DuckDB', status: 'Adapter pending', description: 'First planned engine integration based on the dedupe-system-splink repository.' },
  { id: 'MDL-0002', name: 'Future model slot', family: 'Classification / scoring', version: 'Not registered', runtime: 'Adapter interface', status: 'Planned', description: 'Reserved integration slot. No model is connected.' },
]

// activityFeed is now managed via state in App()

const formatDate = () => new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date())
const cx = (...values) => values.filter(Boolean).join(' ')

function StatusPill({ value }) {
  const state = String(value || '').toLowerCase()
  const type = state.includes('complete') || state === 'validated' || state === 'connected' || state === 'active' || state === 'match' ? 'good'
    : state.includes('review') || state.includes('mapping') || state === 'draft' || state.includes('pending') || state === 'planned' ? 'warning'
    : state.includes('fail') || state.includes('error') || state === 'disconnected' ? 'bad' : 'neutral'
  return <span className={`status-pill ${type}`}><i />{value}</span>
}

function Button({ children, icon: Icon, variant = 'secondary', size = '', disabled = false, onClick, className = '', type = 'button' }) {
  return <button type={type} disabled={disabled} onClick={onClick} className={cx('button', variant, size, className)}>{Icon && <Icon size={15} strokeWidth={1.9} />}{children}</button>
}

function Card({ children, className = '', padding = '' }) {
  return <section className={cx('card', padding, className)}>{children}</section>
}

function PageHeader({ title, subtitle, eyebrow = 'DATA INTELLIGENCE', actions }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow} <span>/</span> {title.toUpperCase()}</div><h1>{title}</h1><p>{subtitle}</p></div><div className="page-actions">{actions}</div></div>
}

function MetricCard({ label, value, change, caption, icon: Icon, tone = 'blue', trend = 'up' }) {
  return <Card className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={18} /></span></div><div className="metric-value">{value}</div><div className="metric-bottom"><span className={trend === 'down' ? 'trend-down' : 'trend-up'}>{trend === 'down' ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}{change}</span><span>{caption}</span></div></Card>
}

function Table({ columns, rows, empty = 'No records found', rowKey = 'id' }) {
  return <div className="table-scroll"><table className="data-table"><thead><tr>{columns.map((column) => <th key={column.key} className={column.className || ''}>{column.label}</th>)}</tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={row[rowKey] || index}>{columns.map((column) => <td key={column.key} className={column.className || ''}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>) : <tr><td colSpan={columns.length}><div className="empty-inline"><SearchX size={18} />{empty}</div></td></tr>}</tbody></table></div>
}

function Field({ label, hint, children }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

function MiniBars({ values }) {
  return <div className="mini-bars" aria-hidden="true">{values.map((value, index) => <span key={index} style={{ height: `${value}%` }} />)}</div>
}

function TrendChart() {
  const values = [37, 48, 43, 61, 56, 71, 66, 78, 68, 84, 76, 91]
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 620},${150 - value * 1.28}`).join(' ')
  const area = `0,150 ${points} 620,150`
  return <div className="trend-chart"><div className="chart-y-labels"><span>120k</span><span>90k</span><span>60k</span><span>30k</span><span>0</span></div><svg viewBox="0 0 620 160" preserveAspectRatio="none" role="img" aria-label="Illustrative 12 period processed records trend"><defs><linearGradient id="trend-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#4B83F0" stopOpacity=".24"/><stop offset="100%" stopColor="#4B83F0" stopOpacity="0"/></linearGradient></defs>{[20,55,90,125,150].map(y => <line key={y} x1="0" x2="620" y1={y} y2={y} stroke="#e9edf4" strokeDasharray="4 5" />)}<polygon points={area} fill="url(#trend-fill)"/><polyline points={points} fill="none" stroke="#4B83F0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/><circle cx="620" cy={150 - values.at(-1) * 1.28} r="5" fill="#fff" stroke="#4B83F0" strokeWidth="3"/></svg><div className="chart-x-labels"><span>01 Nov</span><span>04 Nov</span><span>07 Nov</span><span>10 Nov</span><span>13 Nov</span><span>16 Nov</span><span>19 Nov</span></div></div>
}

function Donut({ segments = [68, 22, 10] }) {
  const total = segments.reduce((sum, value) => sum + value, 0)
  let offset = 0
  const colors = ['#32A789', '#E7AB4C', '#A9B4C6']
  return <svg className="donut-svg" viewBox="0 0 120 120" aria-label="Illustrative decision distribution"><circle cx="60" cy="60" r="43" fill="none" stroke="#edf0f5" strokeWidth="13"/>{segments.map((value, index) => { const dash = (value / total) * 270.2; const node = <circle key={index} cx="60" cy="60" r="43" fill="none" stroke={colors[index]} strokeWidth="13" strokeDasharray={`${dash} ${270.2 - dash}`} strokeDashoffset={-offset} transform="rotate(-90 60 60)" strokeLinecap="butt"/>; offset += dash; return node })}<text x="60" y="57" textAnchor="middle" className="donut-value">2.4M</text><text x="60" y="72" textAnchor="middle" className="donut-label">pairs</text></svg>
}

function App() {
  const [activePage, setActivePage] = useState('dashboard')
  const [dark, setDark] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileMenu, setMobileMenu] = useState(false)
  const [globalSearch, setGlobalSearch] = useState('')
  const [toast, setToast] = useState('')
  const [datasets, setDatasets] = useState(initialDatasets)
  const [runs, setRuns] = useState(initialRuns)
  const [reviews, setReviews] = useState(reviewSeed)
  const [activityFeed, setActivityFeed] = useState([
    { icon: CheckCircle2, title: 'Processing run completed', detail: 'RUN-0268 · crm_customers_q4.csv', time: '08:46 AM', tone: 'mint' },
    { icon: ListChecks, title: 'Review queue updated', detail: '1,284 record pairs await a decision', time: '08:43 AM', tone: 'amber' },
    { icon: Database, title: 'Dataset validated', detail: 'crm_customers_q4.csv · 18 columns', time: '08:42 AM', tone: 'blue' },
    { icon: ShieldCheck, title: 'Database connection checked', detail: 'Analytics PostgreSQL · read-only test', time: 'Yesterday', tone: 'violet' },
  ])

  useEffect(() => {
    fetch('/api/activity', { headers: { 'x-api-key': 'nexus-local-development-key' } })
      .then(res => res.json())
      .then(data => {
        if (data.activities && Array.isArray(data.activities)) {
          const mapped = data.activities.map(act => {
            const iconMap = { review: ListChecks, dataset: Database, run: Workflow }
            return {
              icon: iconMap[act.type] || CheckCircle2,
              title: act.title,
              detail: act.detail,
              time: act.time ? new Date(act.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent',
              tone: act.tone || 'blue'
            }
          })
          setActivityFeed(mapped)
        }
      })
      .catch(() => {})
  }, [])
  const [selectedReview, setSelectedReview] = useState(reviewSeed[0])
  const [reviewTab, setReviewTab] = useState('queue')
  const [datasetFilter, setDatasetFilter] = useState('All')
  const [datasetSearch, setDatasetSearch] = useState('')
  const [runFilter, setRunFilter] = useState('All')
  const [sourceTab, setSourceTab] = useState('files')
  const [models, setModels] = useState(modelSeed)
  const [jobDataset, setJobDataset] = useState(initialDatasets[0].id)
  const [jobEngine, setJobEngine] = useState('MDL-0001')
  const [jobName, setJobName] = useState('Customer deduplication · Q4')
  const [jobRunning, setJobRunning] = useState(false)
  const [runComplete, setRunComplete] = useState(false)
  const [runStep, setRunStep] = useState(0)
  const [showSourceModal, setShowSourceModal] = useState(false)
  const [showModelModal, setShowModelModal] = useState(false)
  const [connectionName, setConnectionName] = useState('Analytics PostgreSQL')
  const [modelName, setModelName] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('Not tested')
  const [sourceType, setSourceType] = useState('PostgreSQL')
  const [outputTable, setOutputTable] = useState('di_results.customer_linkage')
  const [reviewSearch, setReviewSearch] = useState('')
  const [reviewDecisionFilter, setReviewDecisionFilter] = useState('All')
  const [showNotifications, setShowNotifications] = useState(false)
  const fileInputRef = useRef(null)
  const toastTimer = useRef(null)
  const [liveState, setLiveState] = useState('loading')
  const [liveStats, setLiveStats] = useState(null)
  const [liveModel, setLiveModel] = useState(null)
  const [liveError, setLiveError] = useState('')
  const [pairDetail, setPairDetail] = useState(null)
  const [pairDetailLoading, setPairDetailLoading] = useState(false)
  const [pairDetailError, setPairDetailError] = useState('')

  const navItem = navigation.flatMap(group => group.items).find(item => item.id === activePage)
  const meta = pageMeta[activePage]
  const visibleDatasets = useMemo(() => datasets.filter(item => (datasetFilter === 'All' || item.status === datasetFilter) && `${item.name} ${item.id} ${item.source}`.toLowerCase().includes(datasetSearch.toLowerCase())), [datasets, datasetFilter, datasetSearch])
  const visibleRuns = useMemo(() => runs.filter(run => runFilter === 'All' || run.status === runFilter), [runs, runFilter])
  const visibleReviews = useMemo(() => reviews.filter(row => (reviewDecisionFilter === 'All' || row.decision === reviewDecisionFilter) && `${row.id} ${row.left} ${row.right} ${row.reason}`.toLowerCase().includes(reviewSearch.toLowerCase())), [reviews, reviewDecisionFilter, reviewSearch])
  const globalSearchResults = useMemo(() => {
    const query = globalSearch.trim().toLowerCase()
    if (!query) return []
    const pages = navigation.flatMap(group => group.items).filter(item => item.label.toLowerCase().includes(query)).map(item => ({ type: 'page', id: item.id, title: item.label, detail: 'Open workspace page' }))
    const data = datasets.filter(item => `${item.name} ${item.id}`.toLowerCase().includes(query)).slice(0, 4).map(item => ({ type: 'dataset', id: item.id, title: item.name, detail: `Dataset · ${item.status}` }))
    const history = runs.filter(item => `${item.id} ${item.dataset}`.toLowerCase().includes(query)).slice(0, 3).map(item => ({ type: 'run', id: item.id, title: item.id, detail: `Run · ${item.dataset}` }))
    return [...pages, ...data, ...history].slice(0, 7)
  }, [globalSearch, datasets, runs])

  const flash = (message) => {
    setToast(message)
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 3600)
  }
  const navigate = (id) => {
    setActivePage(id)
    setGlobalSearch('')
    setMobileMenu(false)
  }
  const loadLive = async () => {
    try {
      await getHealth()
      const [stats, model, pairs] = await Promise.all([
        getStats(),
        getModelInfo().catch(() => null),
        getPairs(1, 50, 'REVIEW').catch(() => null),
      ])
      setLiveStats(stats)
      setLiveModel(model)
      if (pairs?.pairs?.length) {
        const rows = pairs.pairs.map(toReviewRow)
        setReviews(rows)
        setSelectedReview(rows[0])
      }
      setLiveError('')
      setLiveState('live')
    } catch (error) {
      setLiveError(error.message || String(error))
      setLiveState('offline')
    }
  }
  useEffect(() => { loadLive() }, [])
  useEffect(() => {
  const leftId = selectedReview?.left
  const rightId = selectedReview?.right

  if (!leftId || !rightId) {
    setPairDetail(null)
    return
  }

  let cancelled = false

  const loadPairDetail = async () => {
    setPairDetail(null)
    setPairDetailError('')
    setPairDetailLoading(true)

    try {
      const detail = await dedupApi.getPairDetail(leftId, rightId)

      if (!cancelled) {
        setPairDetail(detail)
      }
    } catch (error) {
      if (!cancelled) {
        setPairDetailError(error.message || 'Failed to load pair detail.')
      }
    } finally {
      if (!cancelled) {
        setPairDetailLoading(false)
      }
    }
  }

  loadPairDetail()

  return () => {
    cancelled = true
  }
}, [selectedReview?.left, selectedReview?.right])
  const selectFile = async (file) => {
    if (!file) return

    // Read file bytes and normalize column names for backend validation
    const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    let fileBytes

    try {
      if (suffix === '.csv') {
        fileBytes = await file.arrayBuffer()
      } else if (suffix === '.parquet') {
        fileBytes = await file.arrayBuffer()
      } else {
        flash('Only CSV and Parquet files are supported')
        return
      }
    } catch (e) {
      flash(`Error reading file: ${e.message || e}`)
      return
    }

    // Normalize CSV column names to lowercase so backend validation passes
    // The backend expects exactly: record_id, first_name, last_name
    if (suffix === '.csv') {
      const textDecoder = new TextDecoder()
      const rawText = textDecoder.decode(fileBytes)
      // Parse header line and normalize column names
      const headerLine = rawText.split('\n')[0]
      const normalizedHeaders = headerLine.split(',').map(h => h.trim().toLowerCase())
      // Reconstruct CSV with normalized headers
      const dataRows = rawText.split('\n').slice(1).filter(r => r.trim())
      const normalizedCsv = [normalizedHeaders.join(','), ...dataRows].join('\n')
      // Create a new file with normalized headers
      const normalizedBlob = new Blob([normalizedCsv], { type: 'text/csv;charset=utf-8' })
      // Replace file with normalized version
      const fileEntry = file
      file = new File([normalizedBlob], file.name, { type: 'text/csv;charset=utf-8' })
    }

    const datasetId = `DS-${String(143 + datasets.length - initialDatasets.length).padStart(4, '0')}`
    setDatasets(current => [{ id: datasetId, name: file.name, source: 'File upload', rows: 'Pending', columns: '—', status: 'Draft', updated: 'Just now', size: `${(file.size / (1024 * 1024)).toFixed(1)} MB` }, ...current])

    // Upload to backend
    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch('/api/datasets/upload', {
        method: 'POST',
        headers: { 'x-api-key': 'nexus-local-development-key' },
        body: formData
      })

      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`Upload failed: ${response.status} ${errText}`)
      }

      const result = await response.json()
      flash(`${file.name} uploaded and validated successfully.`)
      // Refresh datasets list
      await loadDatasets()
    } catch (e) {
      flash(`Upload error: ${e.message || e}`)
    }
  }
  const runPipeline = async () => {
    if (!jobDataset || !jobEngine) return flash('Choose a dataset and processing engine first.')
    if (jobRunning) return
    setJobRunning(true)
    setRunComplete(false)
    setRunStep(1)
    flash('Mengirim job dedup ke FastAPI…')
    try {
      const result = await runDedup([], 'sample')
      setRunStep(6)
      await reload()
      await loadLive()
      const dataset = datasets.find(item => item.id === jobDataset)
      const decisions = result.decisions || {}
      const newRun = {
        id: `RUN-${String(269 + runs.length - initialRuns.length).padStart(4, '0')}`,
        dataset: dataset?.name || 'Selected dataset',
        engine: liveModel?.model_version ? `Splink ${liveModel.model_version}` : 'Splink',
        status: 'Completed',
        records: result.total_records ?? dataset?.rows ?? '—',
        matched: decisions.MATCH ?? '—',
        review: decisions.REVIEW ?? '—',
        started: 'Just now',
        duration: result.runtime_seconds != null ? `${result.runtime_seconds}s` : '—',
        output: 'outputs/splink_predictions_sample.parquet',
      }
      setRuns(current => [newRun, ...current])
      setRunStep(7)
      setRunComplete(true)
      flash(result.status === 'success' ? `Dedup selesai: ${result.pairs_scored} pairs, ${result.runtime_seconds}s.` : `Dedup gagal: ${result.message || 'unknown'}`)
    } catch (error) {
      flash(`Gagal menjalankan dedup: ${error.message || error}`)
    } finally {
      setJobRunning(false)
    }
  }
  const decideReview = (decision) => {
    if (!selectedReview) return
    setReviews(current => current.map(item => item.id === selectedReview.id ? { ...item, decision } : item))
    setSelectedReview(current => ({ ...current, decision }))
    flash(`${selectedReview.id} marked ${decision}. Saved only in local prototype state.`)
  }
  const exportReviews = () => {
    const rows = [['pair_id', 'left_record', 'right_record', 'score', 'decision', 'evidence'], ...reviews.map(row => [row.id, row.left, row.right, row.score, row.decision, row.reason])]
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'nexus-review-sample.csv'
    link.click()
    URL.revokeObjectURL(url)
    flash('Sample review CSV exported.')
  }
  const addModel = () => {
    if (!modelName.trim()) return
    const id = `MDL-${String(models.length + 1).padStart(4, '0')}`
    setModels(current => [...current, { id, name: modelName.trim(), family: 'Custom processing engine', version: 'Unversioned', runtime: 'Adapter not connected', status: 'Planned', description: 'Local registry placeholder. Add a backend adapter before execution.' }])
    setModelName('')
    setShowModelModal(false)
    flash('Model placeholder added to the local registry.')
  }

  const renderDashboard = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<><div className="date-control"><CalendarDays size={15}/>{formatDate()} <ChevronDown size={13}/></div><Button icon={Download} onClick={() => flash('Dashboard report export is not connected yet.')}>Export report</Button></>} />
    <div className="welcome-strip"><div className="welcome-symbol"><Sparkles size={20}/></div><div><b>{liveState === 'live' ? 'Live data from FastAPI' : liveState === 'offline' ? 'Backend unavailable' : 'Connecting to FastAPI…'}</b><p>{liveState === 'live' ? 'KPI di bawah dibaca dari /api/stats. Grafik dan aktivitas lain tetap ilustratif.' : liveState === 'offline' ? `Gagal menghubungi backend: ${liveError}. Halaman lain tetap memakai data sample.` : 'Menunggu respon backend.'}</p></div><span className="demo-badge">{liveState === 'live' ? 'LIVE' : liveState === 'offline' ? 'OFFLINE' : 'CONNECTING'}</span></div>
    <div className="metrics-grid">
      <MetricCard label="Pairs scored" value={liveStats ? liveStats.total_pairs.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : 'OFFLINE'} caption="dari /api/stats" icon={Layers3} tone="blue" />
      <MetricCard label="Matches" value={liveStats ? liveStats.matches.toLocaleString() : '—'} change={liveState === 'live' ? 'auto-merge' : '—'} caption="match_threshold" icon={Workflow} tone="violet" />
      <MetricCard label="Awaiting review" value={liveStats ? liveStats.review.toLocaleString() : '—'} change={liveState === 'live' ? 'perlu keputusan' : '—'} caption="review queue" icon={ListChecks} tone="amber" trend="down" />
      <MetricCard label="Non-matches" value={liveStats ? liveStats.non_matches.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : '—'} caption="dari /api/stats" icon={CheckCheck} tone="mint" />
    </div>
    <div className="dashboard-grid">
      <Card className="chart-card"><div className="card-header"><div><h3>Processing activity</h3><p>Records processed over the last 19 days</p></div><div className="chart-legend"><span><i/> Processed records</span><button onClick={() => flash('Chart range selector is a prototype control.')}>Last 19 days <ChevronDown size={13}/></button></div></div><TrendChart/><div className="chart-foot"><span><i className="legend-dot blue"/> Total processed <b>103,858</b></span><span><i className="legend-dot pale"/> Average / day <b>5,466</b></span></div></Card>
      <Card className="distribution-card"><div className="card-header"><div><h3>Decision distribution</h3><p>Illustrative output classification</p></div><button className="icon-button" onClick={() => navigate('analytics')}><ArrowRight size={16}/></button></div><div className="donut-wrap"><Donut/><div className="donut-legend"><div><i className="green"/><span>Matched</span><b>68%</b></div><div><i className="amber"/><span>Review</span><b>22%</b></div><div><i className="grey"/><span>Non-match</span><b>10%</b></div></div></div><div className="distribution-note"><CircleAlert size={14}/> Threshold and decision counts depend on model configuration.</div></Card>
      <Card className="runs-card"><div className="card-header"><div><h3>Recent processing runs</h3><p>Latest activity across your workspace</p></div><button className="text-link" onClick={() => navigate('history')}>View all <ArrowRight size={14}/></button></div><div className="compact-run-list">{runs.slice(0, 4).map((run) => <div className="compact-run" key={run.id}><div className="run-symbol"><Workflow size={16}/></div><div className="compact-run-main"><b>{run.id} <span>· {run.dataset}</span></b><small>{run.started} <i/> {run.duration}</small></div><StatusPill value={run.status}/></div>)}</div></Card>
      <Card className="activity-card"><div className="card-header"><div><h3>Workspace activity</h3><p>Recent operational events</p></div><button className="icon-button" onClick={() => flash('Activity feed refreshed in demo mode.')}><RefreshCw size={15}/></button></div><div className="activity-list">{activityFeed.map((item, index) => { const Icon = item.icon; return <div className="activity-item" key={index}><span className={`activity-symbol ${item.tone}`}><Icon size={15}/></span><div><b>{item.title}</b><p>{item.detail}</p></div><small>{item.time}</small></div> })}</div></Card>
    </div>
    <div className="bottom-grid"><Card className="quick-card"><div className="card-header"><div><h3>Quick actions</h3><p>Start a common data task</p></div></div><div className="quick-actions"><button onClick={() => navigate('sources')}><span className="quick-icon blue"><CloudUpload size={18}/></span><b>Import data</b><small>Upload a file or connect a source</small><ArrowRight size={16}/></button><button onClick={() => navigate('processing')}><span className="quick-icon violet"><Play size={18}/></span><b>New processing run</b><small>Configure and execute a pipeline</small><ArrowRight size={16}/></button><button onClick={() => navigate('review')}><span className="quick-icon amber"><ListChecks size={18}/></span><b>Review matches</b><small>Resolve uncertain record pairs</small><ArrowRight size={16}/></button></div></Card><Card className="engine-card"><div className="engine-head"><span className="engine-icon"><BrainCircuit size={19}/></span><span className="engine-state"><i/> {liveState === 'live' ? 'Connected' : liveState === 'offline' ? 'Offline' : 'Checking…'}</span></div><h3>Splink CRM Linkage</h3><p>First processing engine planned from the existing deduplication repository.</p><div className="engine-meta"><span>Runtime <b>Python · DuckDB</b></span><span>Adapter <b>{liveState === 'live' ? (liveModel?.model_version || 'Connected') : 'Pending'}</b></span></div><button className="text-link" onClick={() => navigate('models')}>View model registry <ArrowRight size={14}/></button></Card></div>
  </>

  const renderSources = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<Button variant="primary" icon={Plus} onClick={() => setShowSourceModal(true)}>Add connection</Button>} />
    <div className="source-summary-grid"><MetricCard label="Registered sources" value="04" change="2 files" caption="2 database tables" icon={Database} tone="blue"/><MetricCard label="Healthy connections" value="01 / 02" change="50%" caption="database checks" icon={ShieldCheck} tone="mint"/><MetricCard label="Imported datasets" value={String(datasets.length).padStart(2,'0')} change="+1" caption="in this workspace" icon={FileSpreadsheet} tone="violet"/></div>
    <Card className="source-tabs-card"><div className="tab-row"><button className={sourceTab === 'files' ? 'selected' : ''} onClick={() => setSourceTab('files')}><FileSpreadsheet size={16}/> File sources</button><button className={sourceTab === 'database' ? 'selected' : ''} onClick={() => setSourceTab('database')}><Database size={16}/> Database connections</button></div>
      {sourceTab === 'files' ? <div className="source-content"><div className="upload-panel"><input ref={fileInputRef} type="file" accept=".csv,.parquet,.xlsx,.json" hidden onChange={event => { selectFile(event.target.files?.[0]); event.target.value = '' }} /><div className="upload-illustration"><CloudUpload size={25}/></div><h3>Bring your data into the workspace</h3><p>Choose a local file to register it as a dataset in this prototype.</p><Button variant="primary" icon={CloudUpload} onClick={() => fileInputRef.current?.click()}>Choose a file</Button><small>CSV, Parquet, XLSX, JSON · File is not sent to a server</small></div><div className="source-guidance"><div><span className="guidance-icon blue"><FileSpreadsheet size={17}/></span><div><b>CSV / tabular files</b><p>Best for structured customer, transaction, and reference data.</p></div></div><div><span className="guidance-icon violet"><HardDrive size={17}/></span><div><b>Parquet files</b><p>Columnar format for efficient analytical workflows.</p></div></div><div><span className="guidance-icon amber"><ShieldCheck size={17}/></span><div><b>Validation before processing</b><p>Check required columns, types, nulls, and mapping before a run.</p></div></div></div></div> : <div className="connections-list"><div className="connection-card"><div className="connection-brand"><Database size={21}/></div><div className="connection-info"><div><h3>Analytics PostgreSQL</h3><StatusPill value={connectionStatus}/></div><p>localhost:5432 · analytics · Read-only source</p><small>Last checked: {connectionStatus === 'Demo checked' ? 'Just now (demo only)' : 'Not checked'}</small></div><div className="connection-actions"><Button onClick={() => {setConnectionStatus('Demo checked'); flash('Demo connection check completed locally. No real database connection was attempted.')}} icon={RefreshCw}>Test connection</Button><Button variant="ghost" icon={MoreHorizontal} onClick={() => flash('Connection management is not connected to a backend.')}/></div></div><div className="connection-card muted-card"><div className="connection-brand faded"><Database size={21}/></div><div className="connection-info"><div><h3>Staging PostgreSQL</h3><StatusPill value="Not configured"/></div><p>Connection details have not been provided.</p><small>Configure credentials securely in the backend environment.</small></div><Button onClick={() => setShowSourceModal(true)} icon={Plus}>Configure</Button></div></div>}
    </Card>
    <Card className="table-card"><div className="card-header"><div><h3>Recently imported datasets</h3><p>Files and tables registered in this workspace</p></div><button className="text-link" onClick={() => navigate('datasets')}>Open datasets <ArrowRight size={14}/></button></div><Table columns={[{key:'name',label:'Dataset',render:r=><div className="dataset-name"><FileSpreadsheet size={16}/><div><b>{r.name}</b><small>{r.id}</small></div></div>},{key:'source',label:'Source'},{key:'rows',label:'Rows'},{key:'status',label:'Status',render:r=><StatusPill value={r.status}/>},{key:'updated',label:'Last updated'}]} rows={datasets.slice(0,4)}/></Card>
  </>

  const renderDatasets = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<><Button icon={RefreshCw} onClick={() => flash('Dataset list refreshed in demo mode.')}>Refresh</Button><Button variant="primary" icon={Plus} onClick={() => navigate('sources')}>Import dataset</Button></>} />
    <div className="metrics-grid compact-metrics"><MetricCard label="Total datasets" value={String(datasets.length).padStart(2,'0')} change="+1" caption="in current workspace" icon={Table2} tone="blue"/><MetricCard label="Validated" value={String(datasets.filter(row=>row.status==='Validated').length).padStart(2,'0')} change="Ready" caption="for pipeline execution" icon={CheckCircle2} tone="mint"/><MetricCard label="Needs attention" value={String(datasets.filter(row=>row.status!=='Validated').length).padStart(2,'0')} change="Action" caption="mapping or validation" icon={AlertTriangle} tone="amber"/></div>
    <Card className="table-card"><div className="table-toolbar"><div className="search-field"><Search size={15}/><input value={datasetSearch} onChange={event=>setDatasetSearch(event.target.value)} placeholder="Search datasets..."/></div><div className="toolbar-right"><div className="select-wrap"><Filter size={14}/><select value={datasetFilter} onChange={event=>setDatasetFilter(event.target.value)}><option>All</option><option>Validated</option><option>Needs mapping</option><option>Draft</option></select></div><Button icon={Download} onClick={() => flash('Dataset inventory export is not connected yet.')}>Export list</Button></div></div><Table columns={[{key:'name',label:'Dataset name',render:r=><div className="dataset-name"><span className="file-type-icon"><FileSpreadsheet size={16}/></span><div><b>{r.name}</b><small>{r.id}</small></div></div>},{key:'source',label:'Source'},{key:'rows',label:'Records',className:'numeric'},{key:'columns',label:'Columns',className:'numeric'},{key:'size',label:'Size'},{key:'status',label:'Validation',render:r=><StatusPill value={r.status}/>},{key:'updated',label:'Updated'},{key:'action',label:'',render:r=><button className="row-action" onClick={()=>flash(`${r.name}: dataset detail panel is planned.`)}><MoreHorizontal size={17}/></button>}]} rows={visibleDatasets}/><div className="table-footer"><span>Showing {visibleDatasets.length} of {datasets.length} datasets</span><div><button disabled><ChevronLeft size={14}/></button><button className="current">1</button><button disabled><ChevronRight size={14}/></button></div></div></Card>
    <div className="info-banner"><ShieldCheck size={17}/><div><b>Validation is separate from processing</b><p>Only validated datasets should be selectable for a production run. Column mapping and source schema checks will be handled by the backend.</p></div></div>
  </>

  const renderProcessing = () => {
    const steps = ['Schema validation', 'Record ID generation', 'Standardization', 'Blocking', 'Probabilistic scoring', 'Decision & review outputs', 'Clustering & master record']
    const descriptions = ['Check required fields and data types', 'Create an internal identifier for each row', 'Normalize configured attributes', 'Generate candidate record pairs', 'Calculate linkage probabilities with the selected engine', 'Assign MATCH / REVIEW / NON_MATCH decisions', 'Build entity groups and master records']
    return <>
      <PageHeader title={meta[0]} subtitle={meta[1]} actions={<div className="draft-label"><span/> Pipeline draft · not saved</div>} />
      <div className="processing-layout"><div className="processing-main"><Card className="config-card"><div className="section-title"><div><span className="section-kicker">01 / INPUT</span><h3>Choose your data</h3><p>Select an existing dataset as the source for this processing run.</p></div><span className="step-status">Required</span></div><div className="form-grid"><Field label="Dataset" hint="Validated datasets are recommended."><select value={jobDataset} onChange={event=>setJobDataset(event.target.value)}>{datasets.map(item=><option key={item.id} value={item.id} disabled={item.status !== 'Validated'}>{item.name} · {item.rows} rows · {item.status}</option>)}</select></Field><Field label="Run name"><input value={jobName} onChange={event=>setJobName(event.target.value)} placeholder="Give this run a name"/></Field></div><div className="selected-source"><span className="file-type-icon"><FileSpreadsheet size={17}/></span><div><b>{datasets.find(item=>item.id===jobDataset)?.name || 'No dataset selected'}</b><small>{datasets.find(item=>item.id===jobDataset)?.rows || '—'} records · {datasets.find(item=>item.id===jobDataset)?.columns || '—'} columns · {datasets.find(item=>item.id===jobDataset)?.source || '—'}</small></div><StatusPill value={datasets.find(item=>item.id===jobDataset)?.status || 'Unknown'}/></div></Card>
      <Card className="config-card"><div className="section-title"><div><span className="section-kicker">02 / ENGINE</span><h3>Select a processing engine</h3><p>Model-specific settings are isolated from the shared platform workflow.</p></div><button className="text-link" onClick={()=>navigate('models')}>Manage registry <ArrowRight size={14}/></button></div><div className="engine-select-list">{models.map(model=><button key={model.id} className={cx('engine-select',jobEngine===model.id&&'selected')} onClick={()=>setJobEngine(model.id)}><span className="engine-select-icon"><BrainCircuit size={18}/></span><span className="engine-select-text"><b>{model.name}</b><small>{model.family} · {model.runtime}</small></span><span className="engine-select-state"><StatusPill value={model.status}/>{jobEngine===model.id&&<CheckCircle2 size={17}/>}</span></button>)}</div><div className="info-banner compact"><CircleAlert size={16}/><div><b>{liveState === 'live' ? 'Splink terhubung' : 'Adapter belum terhubung'}</b><p>{liveState === 'live' ? 'Run pipeline memanggil POST /api/run-dedup lalu reload predictions.' : 'Menunggu backend FastAPI. Tombol Run akan gagal sampai service berjalan.'}</p></div></div></Card>
      <Card className="config-card"><div className="section-title"><div><span className="section-kicker">03 / PIPELINE</span><h3>Processing stages</h3><p>Stages reflect the current deduplication workflow and can be configured per engine.</p></div><button className="text-link" onClick={()=>flash('Pipeline stage configuration is not connected yet.')}>Configure stages <SlidersHorizontal size={14}/></button></div><div className="pipeline-list">{steps.map((step,index)=><div className={cx('pipeline-row',(jobRunning||runComplete)&&index<runStep&&'done',jobRunning&&index===runStep&&'running')} key={step}><span className="pipeline-number">{(jobRunning||runComplete)&&index<runStep?<Check size={14}/>:String(index+1).padStart(2,'0')}</span><div><b>{step}</b><small>{descriptions[index]}</small></div><span className="pipeline-state">{(jobRunning||runComplete)&&index<runStep?'Complete':jobRunning&&index===runStep?'Running':'Pending'}</span></div>)}</div></Card></div>
      <aside className="processing-side"><Card className="run-summary"><div className="card-header"><div><h3>Run summary</h3><p>Review configuration before execution</p></div><span className="summary-icon"><Workflow size={18}/></span></div><div className="summary-pair"><span>Run name</span><b>{jobName || 'Untitled run'}</b></div><div className="summary-pair"><span>Dataset</span><b>{datasets.find(item=>item.id===jobDataset)?.name || '—'}</b></div><div className="summary-pair"><span>Processing engine</span><b>{models.find(item=>item.id===jobEngine)?.name || '—'}</b></div><div className="summary-pair"><span>Output destination</span><b>{outputTable}</b></div><div className="summary-divider"/><div className="run-warning"><ShieldCheck size={16}/><span>Source data remains unchanged. Output writing will require explicit destination confirmation.</span></div><Button variant="primary" className="run-button" icon={jobRunning?RefreshCw:Play} disabled={jobRunning} onClick={runPipeline}>{jobRunning?'Processing…':'Run pipeline'}</Button><Button className="run-button" icon={Save} onClick={()=>flash('Draft saved only in local browser state.')}>Save as draft</Button><small className="demo-note">{liveState === 'live' ? 'Live mode · Splink via FastAPI · no database write' : 'Demo mode · backend unavailable'}</small></Card><Card className="progress-card"><div className="card-header"><div><h3>Execution progress</h3><p>{jobRunning?`Stage ${Math.min(runStep+1,7)} of 7`:runComplete?'Latest demo run completed':'Waiting for a run'}</p></div><Gauge size={18} className="muted-icon"/></div><div className="progress-track"><span style={{width:`${jobRunning||runComplete?Math.min((runStep/7)*100,100):0}%`}}/></div><div className="progress-meta"><b>{jobRunning||runComplete?`${Math.round((runStep/7)*100)}%`:'0%'}</b><span>{jobRunning?'In progress':runComplete?'Completed':'Not started'}</span></div><div className="terminal-box"><div><i/><i/><i/><span>RUN LOG</span></div><code>{jobRunning?`[demo] ${steps[Math.max(0,Math.min(runStep,steps.length-1))]}…`:runComplete?'[demo] Run completed. No engine was executed.':'No execution logs yet.'}</code></div></Card></aside></div>
    </>
  }

  const renderReview = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<><Button icon={Download} onClick={exportReviews}>Export sample</Button><Button variant="primary" icon={CheckCheck} onClick={()=>flash('Bulk decisions require a backend review policy.')}>Bulk actions</Button></>} />
    <div className="review-kpis"><div><span className="kpi-dot amber"/><div><b>{liveStats ? liveStats.review.toLocaleString() : '1,284'}</b><small>Awaiting review</small></div></div><div><span className="kpi-dot mint"/><div><b>{liveState === 'live' ? '—' : '342'}</b><small>{liveState === 'live' ? 'Reviewed today (live)' : 'Reviewed today'}</small></div></div><div><span className="kpi-dot blue"/><div><b>{liveStats && liveStats.total_pairs ? ((liveStats.matches / liveStats.total_pairs) * 100).toFixed(1) + '%' : '86.4%'}</b><small>{liveState === 'live' ? 'Match share (live)' : 'Agreement rate · illustrative'}</small></div></div><div className="review-progress"><div><span>Queue progress</span><b>{liveStats && liveStats.total_pairs ? Math.round((liveStats.review / liveStats.total_pairs) * 100) : 21}%</b></div><div className="progress-track"><span style={{width: `${liveStats && liveStats.total_pairs ? Math.round((liveStats.review / liveStats.total_pairs) * 100) : 21}%`}}/></div></div></div>
    <div className="review-workspace"><Card className="review-list-card"><div className="review-tabs"><button className={reviewTab==='queue'?'selected':''} onClick={()=>setReviewTab('queue')}>Pair queue <span>{reviews?.length}</span></button><button className={reviewTab==='history'?'selected':''} onClick={()=>setReviewTab('history')}>Reviewed history</button></div><div className="table-toolbar review-toolbar"><div className="search-field"><Search size={15}/><input value={reviewSearch} onChange={event=>setReviewSearch(event.target.value)} placeholder="Search record pairs..."/></div><div className="select-wrap"><Filter size={14}/><select value={reviewDecisionFilter} onChange={event=>setReviewDecisionFilter(event.target.value)}><option>All</option><option>REVIEW</option><option>MATCH</option><option>NON_MATCH</option></select></div></div><div className="pair-list">{visibleReviews.filter(row=>reviewTab==='queue'?row.decision==='REVIEW':row.decision!=='REVIEW').map(row=><button key={row.id} className={cx('pair-item',selectedReview?.id===row.id&&'active')} onClick={()=>setSelectedReview(row)}><div className="pair-item-top"><b>{row.id}</b><span className="score-chip">{Math.round(row.score*100)}% score</span></div><div className="pair-names"><span>{row.left}</span><ArrowRight size={13}/><span>{row.right}</span></div><p>{row.reason}</p><div className="pair-item-bottom"><StatusPill value={row.decision}/><small>Updated just now</small></div></button>)}{visibleReviews.filter(row=>reviewTab==='queue'?row.decision==='REVIEW':row.decision!=='REVIEW').length===0&&<div className="empty-state small-empty"><SearchX size={22}/><b>No pairs in this view</b><span>Change the filter or select another tab.</span></div>}</div><div className="review-list-footer"><span>{visibleReviews.length} sample pairs shown</span><button onClick={()=>flash('Pagination is planned for the backend review endpoint.')}>Load more <ChevronDown size={14}/></button></div></Card>
    <Card className="review-detail-card"><div className="review-detail-head"><div><span className="section-kicker">PAIR INSPECTION</span><h3>{selectedReview?.id || 'Select a pair'}</h3><p>Compare source attributes and decision evidence.</p></div><StatusPill value={selectedReview?.decision || 'No selection'}/></div>
    {selectedReview && (
  <>
    {pairDetailLoading && (
      <div className="empty-state small-empty">
        <RefreshCw size={18} />
        <span>Loading customer records and model evidence...</span>
      </div>
    )}

    {pairDetailError && (
      <div className="empty-state small-empty">
        <CircleAlert size={18} />
        <b>Could not load pair detail</b>
        <span>{pairDetailError}</span>
      </div>
    )}

    {pairDetail && (
      <>
        <div className="record-compare">
          <div className="record-card">
          <span className="record-label">RECORD A</span>

          <h4>
            {pairDetail.record_a?.record_id || '—'}
          </h4>

          <div>
            <small>Email</small>
            <b>{pairDetail.record_a?.email || '—'}</b>
          </div>

          <div>
            <small>Full Name</small>
            <b>
              {[
                pairDetail.record_a?.first_name,
                pairDetail.record_a?.last_name
              ].filter(Boolean).join(' ') || '—'}
            </b>
          </div>

          <div>
            <small>Phone</small>
            <b>{pairDetail.record_a?.phone_number || '—'}</b>
          </div>

          <div>
            <small>Date of Birth</small>
            <b>{pairDetail.record_a?.dob || '—'}</b>
          </div>

          <div>
            <small>Full Address</small>
            <b>
              {[
                pairDetail.record_a?.address,
                pairDetail.record_a?.city,
                pairDetail.record_a?.state,
                pairDetail.record_a?.country
              ].filter(Boolean).join(', ') || '—'}
            </b>
          </div>
        </div>

        <div className="compare-divider"><span>VS</span></div>

          <div className="record-card">
          <span className="record-label">RECORD B</span>

          <h4>
            {pairDetail.record_b?.record_id || '—'}
          </h4>

          <div>
            <small>Email</small>
            <b>{pairDetail.record_b?.email || '—'}</b>
          </div>

          <div>
            <small>Full Name</small>
            <b>
              {[
                pairDetail.record_b?.first_name,
                pairDetail.record_b?.last_name
              ].filter(Boolean).join(' ') || '—'}
            </b>
          </div>

          <div>
            <small>Phone</small>
            <b>{pairDetail.record_b?.phone_number || '—'}</b>
          </div>

          <div>
            <small>Date of Birth</small>
            <b>{pairDetail.record_b?.dob || '—'}</b>
          </div>

          <div>
            <small>Full Address</small>
            <b>
              {[
                pairDetail.record_b?.address,
                pairDetail.record_b?.city,
                pairDetail.record_b?.state,
                pairDetail.record_b?.country
              ].filter(Boolean).join(', ') || '—'}
            </b>
          </div>
        </div>
        </div>

        <div className="match-evidence">
          <div className="evidence-head">
            <div>
              <b>Model Evidence · Splink</b>
              <small>Live prediction output from backend</small>
            </div>
            <strong>
              {(Number(pairDetail.match_probability) * 100).toFixed(2)}
              <small>%</small>
            </strong>
          </div>

          <div className="evidence-track">
            <span style={{
              width: `${Math.max(0, Math.min(100, Number(pairDetail.match_probability) * 100))}%`
            }} />
          </div>

          <div className="evidence-flags">
            <span className="flag-neutral">Decision: {pairDetail.decision}</span>
            <span className="flag-neutral">Match weight: {Number(pairDetail.evidence?.match_weight).toFixed(4)}</span>
          </div>

          <div className="evidence-grid">
            <div><small>Gamma name</small><b>{pairDetail.evidence?.gamma_name ?? '—'}</b></div>
            <div><small>Gamma contact</small><b>{pairDetail.evidence?.gamma_contact ?? '—'}</b></div>
            <div><small>Gamma location</small><b>{pairDetail.evidence?.gamma_location ?? '—'}</b></div>
            <div><small>Gamma DoB</small><b>{pairDetail.evidence?.gamma_dob ?? '—'}</b></div>
            <div><small>Match key</small><b>{pairDetail.evidence?.match_key ?? '—'}</b></div>
            <div><small>Business rule</small><b>{pairDetail.evidence?.business_rule ?? '—'}</b></div>
          </div>

          <p>
            Probability and comparison levels are displayed from the Splink
            prediction output. Gamma values are comparison-level codes, not
            percentages or direct similarity scores.
          </p>
        </div>
      </>
    )}

    <div className="decision-panel">
      <b>Human decision</b>
      <p>
        Choose whether these records represent the same entity.
        The decision is currently stored only in local prototype state.
      </p>
      <div className="decision-buttons">
        <Button
          variant="success"
          icon={CheckCheck}
          onClick={() => decideReview('MATCH')}
        >
          Confirm match
        </Button>
        <Button
          variant="danger"
          icon={X}
          onClick={() => decideReview('NON_MATCH')}
        >
          Not a match
        </Button>
        <Button
          icon={Clock3}
          onClick={() => flash('Pair kept in review state.')}
        >
          Keep in review
        </Button>
      </div>
    </div>
  </>
)}
    </Card>
    </div>
  </>

  const renderHistory = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<Button icon={Download} onClick={()=>flash('Run history export is not connected yet.')}>Export history</Button>} />
    <div className="metrics-grid compact-metrics"><MetricCard label="Total runs" value="28" change="+5" caption="this month" icon={Workflow} tone="blue"/><MetricCard label="Successful" value="24" change="85.7%" caption="completion rate" icon={CheckCircle2} tone="mint"/><MetricCard label="Needs attention" value="03" change="Review" caption="manual action required" icon={AlertTriangle} tone="amber"/></div>
    <Card className="table-card"><div className="table-toolbar"><div className="table-heading"><h3>Processing runs</h3><p>Latest executions across datasets and engines</p></div><div className="toolbar-right"><div className="select-wrap"><Filter size={14}/><select value={runFilter} onChange={event=>setRunFilter(event.target.value)}><option>All</option><option>Completed</option><option>Needs review</option><option>Failed</option><option>Completed (demo)</option></select></div><Button icon={RefreshCw} onClick={()=>flash('Run history refreshed in demo mode.')}>Refresh</Button></div></div><Table columns={[{key:'id',label:'Run ID',render:r=><b className="mono-link">{r.id}</b>},{key:'dataset',label:'Dataset',render:r=><div className="table-primary"><b>{r.dataset}</b><small>{r.engine}</small></div>},{key:'status',label:'Status',render:r=><StatusPill value={r.status}/>},{key:'records',label:'Records',className:'numeric'},{key:'matched',label:'Matches',className:'numeric'},{key:'review',label:'Review',className:'numeric'},{key:'started',label:'Started'},{key:'duration',label:'Duration'},{key:'action',label:'',render:r=><button className="row-action" onClick={()=>flash(`${r.id}: run detail page is planned.`)}><MoreHorizontal size={17}/></button>}]} rows={visibleRuns}/><div className="table-footer"><span>Showing {visibleRuns.length} runs</span><div><button disabled><ChevronLeft size={14}/></button><button className="current">1</button><button disabled><ChevronRight size={14}/></button></div></div></Card>
    <Card className="output-card"><div className="card-header"><div><h3>Output destinations</h3><p>Results are written only after explicit confirmation in the real platform.</p></div><Database size={18} className="muted-icon"/></div><div className="output-row"><div className="output-icon"><Table2 size={18}/></div><div><b>di_results.run_0268</b><small>PostgreSQL · proposed destination · not written by this prototype</small></div><StatusPill value="Illustrative"/><button className="icon-button" onClick={()=>flash('Destination details are not connected.') }><ExternalLink size={15}/></button></div></Card>
  </>

  const renderModels = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<Button variant="primary" icon={Plus} onClick={()=>setShowModelModal(true)}>Register model</Button>} />
    <div className="info-banner"><BrainCircuit size={18}/><div><b>Model-independent by design</b><p>The platform talks to engines through adapters. Each adapter defines metadata, accepted inputs, execution settings, outputs, and status.</p></div></div>
    <div className="model-grid">{models.map((model,index)=><Card className="model-card" key={model.id}><div className="model-card-top"><span className="model-art"><BrainCircuit size={22}/></span><StatusPill value={model.status}/></div><div className="model-id">{model.id}</div><h3>{model.name}</h3><p>{model.description}</p><div className="model-specs"><div><span>Family</span><b>{model.family}</b></div><div><span>Version</span><b>{model.version}</b></div><div><span>Runtime</span><b>{model.runtime}</b></div></div><div className="model-card-foot"><span><i className={index===0?'dot-amber':'dot-grey'}/>{index===0?'Integration queued':'Not connected'}</span><button className="text-link" onClick={()=>flash(`${model.name}: adapter configuration is not available yet.`)}>Details <ArrowRight size={14}/></button></div></Card>)}</div>
    <Card className="adapter-contract"><div className="card-header"><div><h3>Adapter contract</h3><p>Proposed integration boundary between FastAPI and model runtimes.</p></div><span className="contract-tag"><Code2 size={14}/> Interface draft</span></div><div className="contract-grid"><div><b>describe()</b><small>Model metadata, version, capabilities</small></div><div><b>validate_input()</b><small>Required fields and schema checks</small></div><div><b>execute()</b><small>Run processing with normalized config</small></div><div><b>get_status()</b><small>Execution state and error details</small></div><div><b>get_outputs()</b><small>Standardized output references</small></div></div><div className="code-note"><Terminal size={14}/><code>Platform API → Adapter registry → Engine service → Result contract</code><button onClick={()=>{navigator.clipboard?.writeText('Platform API → Adapter registry → Engine service → Result contract');flash('Architecture line copied.')}}><Copy size={14}/></button></div></Card>
  </>

  const renderAnalytics = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<div className="date-control"><CalendarDays size={15}/> Last 30 days <ChevronDown size={13}/></div>} />
    <div className="info-banner amber-banner"><CircleAlert size={17}/><div><b>Evaluation data is illustrative</b><p>Do not treat these numbers as validated model performance. Production metrics must be derived from independently reviewed gold labels and documented evaluation splits.</p></div></div>
    <div className="metrics-grid"><MetricCard label="Precision" value="94.2%" change="+1.8 pp" caption="illustrative evaluation" icon={TargetIcon} tone="mint"/><MetricCard label="Recall" value="87.6%" change="+0.9 pp" caption="illustrative evaluation" icon={Gauge} tone="blue"/><MetricCard label="F1 score" value="90.8%" change="+1.2 pp" caption="illustrative evaluation" icon={Activity} tone="violet"/><MetricCard label="Review rate" value="12.4%" change="−2.1 pp" caption="illustrative output share" icon={ListChecks} tone="amber" trend="down"/></div>
    <div className="analytics-grid"><Card className="chart-card"><div className="card-header"><div><h3>Evaluation trend</h3><p>Illustrative precision and recall by evaluation run</p></div><StatusPill value="Sample data"/></div><div className="evaluation-chart"><div className="eval-y-labels"><span>100%</span><span>90%</span><span>80%</span><span>70%</span><span>60%</span></div><svg viewBox="0 0 620 190" preserveAspectRatio="none"><defs><linearGradient id="eval-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#31a889" stopOpacity=".14"/><stop offset="1" stopColor="#31a889" stopOpacity="0"/></linearGradient></defs>{[15,55,95,135,175].map(y=><line key={y} x1="0" x2="620" y1={y} y2={y} stroke="#e9edf4" strokeDasharray="4 5"/>)}<polyline points="0,68 88,58 176,62 264,48 352,44 440,39 528,33 620,28" fill="none" stroke="#31a889" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/><polyline points="0,105 88,99 176,108 264,91 352,83 440,87 528,77 620,70" fill="none" stroke="#4B83F0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/></svg></div><div className="eval-legend"><span><i className="green"/> Precision</span><span><i className="blue"/> Recall</span></div></Card><Card className="quality-card"><div className="card-header"><div><h3>Decision quality</h3><p>Illustrative classification distribution</p></div></div><div className="quality-rows"><div><div><span>MATCH</span><b>68.0%</b></div><div className="quality-track"><i className="green" style={{width:'68%'}}/></div></div><div><div><span>REVIEW</span><b>22.0%</b></div><div className="quality-track"><i className="amber" style={{width:'22%'}}/></div></div><div><div><span>NON_MATCH</span><b>10.0%</b></div><div className="quality-track"><i className="grey" style={{width:'10%'}}/></div></div></div><div className="quality-foot"><span>Review labels available</span><b>342 sample labels</b></div></Card><Card className="evaluation-breakdown"><div className="card-header"><div><h3>Evaluation checklist</h3><p>Evidence required before trusting model metrics</p></div></div><div className="checklist-item"><CheckCircle2 size={16}/><div><b>Gold labels separated from silver labels</b><small>Use human-reviewed labels as the trusted evaluation reference.</small></div><StatusPill value="Required"/></div><div className="checklist-item"><AlertTriangle size={16}/><div><b>Disputed identity cases documented</b><small>Record known conflicts and adjudication decisions.</small></div><StatusPill value="Review"/></div><div className="checklist-item"><CircleDot size={16}/><div><b>Threshold and model version captured</b><small>Store the exact configuration used for every evaluation.</small></div><StatusPill value="Planned"/></div></Card></div>
  </>

  const renderDatabase = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<Button variant="primary" icon={Plus} onClick={()=>setShowSourceModal(true)}>Add connection</Button>} />
    <div className="db-layout"><div className="db-main"><Card className="db-connection"><div className="connection-card large"><div className="connection-brand"><Database size={22}/></div><div className="connection-info"><div><h3>Analytics PostgreSQL</h3><StatusPill value={connectionStatus}/></div><p>Local demo connection profile · credentials are not stored in this frontend.</p><small>Host details are illustrative and not connected to a database.</small></div><Button onClick={()=>{setConnectionStatus('Demo checked');flash('Demo connection check only. No database request was made.')}} icon={RefreshCw}>Test connection</Button></div><div className="db-properties"><div><span>Engine</span><b>PostgreSQL</b></div><div><span>Host</span><b>localhost:5432</b></div><div><span>Database</span><b>analytics</b></div><div><span>Access mode</span><b>Read-only source</b></div></div></Card><Card className="schema-card"><div className="card-header"><div><h3>Schema browser</h3><p>Example schemas and tables for the proposed workspace.</p></div><Button icon={RefreshCw} onClick={()=>flash('Schema refresh requires a real backend connection.')}>Refresh</Button></div><div className="schema-tree"><div className="schema-root"><Database size={16}/><b>analytics</b><span>Database</span></div>{[['public',['customers','customer_addresses','transactions']],['staging',['leads_import','customer_delta']],['di_results',['run_0268','run_0267']]].map(([schema,tables])=><div className="schema-group" key={schema}><div><ChevronDown size={14}/><Layers3 size={15}/><b>{schema}</b><small>{tables.length} tables</small></div>{tables.map(table=><button key={table} onClick={()=>flash(`Table ${schema}.${table} selected in demo schema browser.`)}><Table2 size={14}/>{table}<span>View columns <ChevronRight size={12}/></span></button>)}</div>)}</div></Card></div><div className="db-side"><Card className="output-config"><div className="card-header"><div><h3>Output destination</h3><p>Default table for future processing results</p></div><Table2 size={18}/></div><Field label="Output schema"><select defaultValue="di_results"><option value="di_results">di_results</option><option value="public">public</option><option value="staging">staging</option></select></Field><Field label="Output table"><input value={outputTable.split('.').at(-1)} onChange={event=>setOutputTable(`di_results.${event.target.value}`)}/></Field><div className="output-safety"><ShieldCheck size={15}/><span>Source tables are never overwritten by default. Destination allowlisting and write permissions must be enforced by FastAPI.</span></div><Button variant="primary" className="full-width" icon={Save} onClick={()=>flash('Output destination saved locally only.')}>Save destination</Button></Card><Card className="security-card"><span className="security-symbol"><ShieldCheck size={19}/></span><h3>Connection security</h3><p>Production credentials must be managed server-side, preferably through environment secrets or a secret manager.</p><ul><li>No database passwords in React</li><li>Use least-privilege database roles</li><li>Restrict writable destination tables</li><li>Audit all write operations</li></ul></Card></div></div>
  </>

  const renderSettings = () => <>
    <PageHeader title={meta[0]} subtitle={meta[1]} actions={<Button variant="primary" icon={Save} onClick={()=>flash('Workspace preferences saved in local demo state.')}>Save changes</Button>} />
    <div className="settings-layout"><Card className="settings-menu"><button className="selected"><Settings size={15}/> General <ChevronRight size={14}/></button><button onClick={()=>flash('Appearance section selected.') }><Sun size={15}/> Appearance <ChevronRight size={14}/></button><button onClick={()=>flash('Processing defaults section selected.') }><Workflow size={15}/> Processing defaults <ChevronRight size={14}/></button><button onClick={()=>flash('Export preferences section selected.') }><Download size={15}/> Export preferences <ChevronRight size={14}/></button><button onClick={()=>flash('Security section selected.') }><ShieldCheck size={15}/> Security <ChevronRight size={14}/></button></Card><div className="settings-content"><Card className="settings-card"><div className="settings-card-title"><div><h3>Workspace profile</h3><p>Identity and regional preferences for this environment.</p></div><Layers3 size={18}/></div><div className="form-grid"><Field label="Workspace name"><input defaultValue="HyperData Intelligence"/></Field><Field label="Timezone"><select defaultValue="Asia/Jakarta"><option>Asia/Jakarta</option><option>UTC</option><option>Asia/Singapore</option></select></Field><Field label="Default landing page"><select defaultValue="dashboard"><option value="dashboard">Overview</option><option value="processing">Processing</option><option value="review">Review queue</option></select></Field><Field label="Date format"><select defaultValue="DD MMM YYYY"><option>DD MMM YYYY</option><option>YYYY-MM-DD</option><option>MM/DD/YYYY</option></select></Field></div></Card><Card className="settings-card"><div className="settings-card-title"><div><h3>Appearance</h3><p>Choose a workspace display theme.</p></div><Moon size={18}/></div><div className="theme-choices"><button className={!dark?'chosen':''} onClick={()=>setDark(false)}><div className="theme-thumb light-thumb"><i/><i/><i/></div><b>Light</b><small>Bright and clean</small></button><button className={dark?'chosen':''} onClick={()=>setDark(true)}><div className="theme-thumb dark-thumb"><i/><i/><i/></div><b>Dark</b><small>Low-light workspace</small></button></div></Card><Card className="settings-card"><div className="settings-card-title"><div><h3>Processing defaults</h3><p>Safe defaults applied when creating a new run.</p></div><SlidersHorizontal size={18}/></div><div className="setting-toggle"><div><b>Preserve source data</b><small>Never overwrite the original source dataset.</small></div><button className="toggle-switch on" onClick={event=>event.currentTarget.classList.toggle('on')}><i/></button></div><div className="setting-toggle"><div><b>Require output confirmation</b><small>Ask for confirmation before writing to a destination table.</small></div><button className="toggle-switch on" onClick={event=>event.currentTarget.classList.toggle('on')}><i/></button></div><div className="setting-toggle"><div><b>Keep processing audit trail</b><small>Store run configuration, status, and output references.</small></div><button className="toggle-switch on" onClick={event=>event.currentTarget.classList.toggle('on')}><i/></button></div></Card><div className="settings-footnote"><ShieldCheck size={15}/> Settings are currently stored in local prototype state. Persistent preferences require backend integration.</div></div></div>
  </>

  const renderPage = () => {
    switch (activePage) {
      case 'dashboard': return renderDashboard()
      case 'sources': return renderSources()
      case 'datasets': return renderDatasets()
      case 'processing': return renderProcessing()
      case 'review': return renderReview()
      case 'history': return renderHistory()
      case 'models': return renderModels()
      case 'analytics': return renderAnalytics()
      case 'database': return renderDatabase()
      case 'settings': return renderSettings()
      default: return renderDashboard()
    }
  }

  return <div className={cx('app-shell', dark && 'dark-theme')}>
    <aside className={cx('sidebar', collapsed && 'collapsed', mobileMenu && 'mobile-open')}>
      <div className="brand-row"><span className="brand-mark"><Layers3 size={19}/></span><div className="brand-copy"><b>Hyperdata</b><small>INTELLIGENCE</small></div><button className="collapse-button" onClick={()=>setCollapsed(value=>!value)} title="Collapse sidebar">{collapsed?<PanelLeftOpen size={16}/>:<PanelLeftClose size={16}/>}</button><button className="mobile-close" onClick={()=>setMobileMenu(false)}><X size={18}/></button></div>
      <button className="workspace-switch" onClick={()=>flash('Workspace switcher is a visual placeholder.')}><span className="workspace-avatar">ND</span><span className="workspace-copy"><b>Data workspace</b><small>Personal environment</small></span><ChevronDown size={14}/></button>
      <nav className="main-nav">{navigation.map(group=><div className="nav-group" key={group.group}><div className="nav-group-label">{group.group}</div>{group.items.map(item=>{const Icon=item.icon;return <button key={item.id} title={collapsed?item.label:''} className={cx('nav-link',activePage===item.id&&'active')} onClick={()=>navigate(item.id)}><Icon size={17} strokeWidth={1.8}/><span>{item.label}</span>{item.count&&<em>{item.count}</em>}{activePage===item.id&&<i className="active-mark"/>}</button>})}</div>)}</nav>
      <div className="sidebar-bottom"><div className="help-card"><span><Sparkles size={15}/></span><div><b>Build something smart</b><small>Explore platform capabilities</small></div><ArrowUpRight size={14}/></div><div className="sidebar-user"><span className="user-avatar">DA</span><div className="sidebar-user-copy"><b>Data Analyst</b><small>Workspace admin</small></div><MoreHorizontal size={17}/></div></div>
    </aside>
    {mobileMenu&&<button className="mobile-backdrop" onClick={()=>setMobileMenu(false)} aria-label="Close navigation"/>}
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu-button" onClick={()=>setMobileMenu(true)}><Menu size={19}/></button><div className="breadcrumb"><span>Workspace</span><ChevronRight size={13}/><b>{navItem?.label || 'Overview'}</b></div></div><div className="topbar-right"><div className="global-search-wrap"><div className="global-search"><Search size={15}/><input value={globalSearch} onChange={event=>setGlobalSearch(event.target.value)} placeholder="Search workspace"/><kbd>⌘ K</kbd></div>{globalSearch.trim()&&<div className="global-search-results">{globalSearchResults.length?globalSearchResults.map(result=><button key={`${result.type}-${result.id}`} onClick={()=>{if(result.type==='page')navigate(result.id);else if(result.type==='dataset')navigate('datasets');else navigate('history');setGlobalSearch('')}}><span>{result.type==='page'?'PAGE':result.type==='dataset'?'DATASET':'RUN'}</span><div><b>{result.title}</b><small>{result.detail}</small></div><ArrowUpRight size={14}/></button>):<div className="search-empty">No workspace results for “{globalSearch}”</div>}</div>}</div><button className="icon-button theme-toggle" onClick={()=>setDark(value=>!value)} title="Toggle theme">{dark?<Sun size={17}/>:<Moon size={17}/>}</button><div className="topbar-separator"/><div className="notification-wrap"><button className="icon-button notification-button" onClick={()=>setShowNotifications(value=>!value)}><Bell size={17}/><i/></button>{showNotifications&&<div className="notification-popover"><b>Notifications</b><p><span/> {liveStats ? `${liveStats.review.toLocaleString()} pairs waiting for human review.` : '1,284 pairs waiting for human review.'}</p><p><span/> {liveState === 'live' ? 'Backend connected · data live from /api/stats' : 'Last processing run completed in demo mode.'}</p><button onClick={()=>setShowNotifications(false)}>Close</button></div>}</div><div className="top-user"><span className="user-avatar small">DA</span><div><b>Data Analyst</b><small>Admin</small></div><ChevronDown size={13}/></div></div></header>
      <div className="content-area">{renderPage()}<footer className="app-footer"><span>© 2026 HyperData Intelligence</span><span className="footer-center"><i/> {liveState === 'live' ? 'API connected · /api proxy → localhost:8000' : liveState === 'offline' ? `Backend unavailable: ${liveError}` : 'Connecting…'}</span><span>Platform UI · v1.1</span></footer></div>
    </main>
    {toast&&<div className="toast"><CheckCircle2 size={16}/><span>{toast}</span><button onClick={()=>setToast('')}><X size={14}/></button></div>}
    {showSourceModal&&<div className="modal-overlay" onMouseDown={event=>{if(event.target===event.currentTarget)setShowSourceModal(false)}}><div className="modal-card"><div className="modal-header"><div><span className="section-kicker">DATA CONNECTOR</span><h2>Add a database connection</h2></div><button className="icon-button" onClick={()=>setShowSourceModal(false)}><X size={17}/></button></div><p className="modal-copy">Create a connection profile. This prototype does not store credentials or establish a live database connection.</p><Field label="Connection name"><input value={connectionName} onChange={event=>setConnectionName(event.target.value)}/></Field><Field label="Database engine"><select value={sourceType} onChange={event=>setSourceType(event.target.value)}><option>PostgreSQL</option><option>DuckDB</option></select></Field><div className="form-grid"><Field label="Host"><input placeholder="localhost"/></Field><Field label="Port"><input placeholder="5432"/></Field><Field label="Database"><input placeholder="analytics"/></Field><Field label="Username"><input placeholder="database user" autoComplete="off"/></Field></div><div className="security-callout"><ShieldCheck size={16}/> Actual credentials must be provided through a secure backend configuration, not this browser form.</div><div className="modal-actions"><Button onClick={()=>setShowSourceModal(false)}>Cancel</Button><Button variant="primary" onClick={()=>{setShowSourceModal(false);flash(`${connectionName} saved as a local placeholder. No connection was made.`)}}>Save placeholder</Button></div></div></div>}
    {showModelModal&&<div className="modal-overlay" onMouseDown={event=>{if(event.target===event.currentTarget)setShowModelModal(false)}}><div className="modal-card"><div className="modal-header"><div><span className="section-kicker">MODEL REGISTRY</span><h2>Register a processing engine</h2></div><button className="icon-button" onClick={()=>setShowModelModal(false)}><X size={17}/></button></div><p className="modal-copy">Create a metadata entry. A compatible backend adapter is required before the engine can be executed.</p><Field label="Model / engine name"><input value={modelName} onChange={event=>setModelName(event.target.value)} placeholder="e.g. Customer risk scoring"/></Field><Field label="Processing family"><select defaultValue="Custom processing engine"><option>Custom processing engine</option><option>Classification</option><option>Regression</option><option>Clustering</option><option>Entity resolution</option><option>Anomaly detection</option></select></Field><div className="security-callout"><Code2 size={16}/> The registry entry is local only. Runtime loading and validation belong to FastAPI.</div><div className="modal-actions"><Button onClick={()=>setShowModelModal(false)}>Cancel</Button><Button variant="primary" onClick={addModel}>Create registry entry</Button></div></div></div>}
  </div>
}

function TargetIcon(props) { return <Gauge {...props}/> }

export default App
