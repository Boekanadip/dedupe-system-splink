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
import { dedupApi, toReviewRow } from './services/dedupApi'

const navigation = [
  { group: 'WORKSPACE', items: [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    { id: 'sources', label: 'Data sources', icon: Database },
    { id: 'datasets', label: 'Datasets', icon: Table2 },
  ]},
  { group: 'OPERATIONS', items: [
    { id: 'processing', label: 'Processing', icon: Workflow },
    { id: 'review', label: 'Review queue', icon: ListChecks },
    { id: 'entities', label: 'Entity management', icon: Layers3 },
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
  entities: ['Entity management', 'Explore resolved customer entities, cluster memberships, and identity conflicts.'],
  history: ['Run history', 'Track processing runs, outcomes, and output destinations.'],
  models: ['Model registry', 'Manage processing engines independently from the platform UI.'],
  analytics: ['Evaluation', 'Monitor data quality, linkage outcomes, and model evaluation.'],
  database: ['Database management', 'Configure PostgreSQL connections and output destinations.'],
  settings: ['Workspace settings', 'Manage workspace preferences and operational defaults.'],
}

const initialDatasets = []

const initialRuns = []

const reviewSeed = []

const modelSeed = [
  { id: 'MDL-0001', name: 'Splink CRM Linkage', family: 'Probabilistic record linkage', version: 'Repository integration', runtime: 'Python · DuckDB', status: 'Adapter pending', description: 'First planned engine integration based on the dedupe-system-splink repository.' },
  { id: 'MDL-0002', name: 'Future model slot', family: 'Classification / scoring', version: 'Not registered', runtime: 'Adapter interface', status: 'Planned', description: 'Reserved integration slot. No model is connected.' },
]

const formatDate = (format, timeZone) => {
  const parts = new Intl.DateTimeFormat('en', {
    day: '2-digit',
    month: format === 'DD MMM YYYY' ? 'short' : '2-digit',
    year: 'numeric',
    timeZone,
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  if (format === 'YYYY-MM-DD') return `${values.year}-${values.month}-${values.day}`
  if (format === 'MM/DD/YYYY') return `${values.month}/${values.day}/${values.year}`
  return `${values.day} ${values.month} ${values.year}`
}
const toDatasetRow = dataset => ({
  id: dataset.id,
  name: dataset.name,
  source: dataset.source || 'File upload',
  rows: dataset.rows,
  columns: dataset.columns,
  size: '—',
  status: dataset.status,
  updated: dataset.updated
    ? new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(dataset.updated))
    : '—',
})
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

function Donut({ segments, total }) {
  let offset = 0
  const colors = ['#32A789', '#E7AB4C', '#A9B4C6']
  return <svg className="donut-svg" viewBox="0 0 120 120" aria-label="Decision distribution from prediction data"><circle cx="60" cy="60" r="43" fill="none" stroke="#edf0f5" strokeWidth="13"/>{segments.map((value, index) => { const dash = (value / total) * 270.2; const node = <circle key={index} cx="60" cy="60" r="43" fill="none" stroke={colors[index]} strokeWidth="13" strokeDasharray={`${dash} ${270.2 - dash}`} strokeDashoffset={-offset} transform="rotate(-90 60 60)" strokeLinecap="butt"/>; offset += dash; return node })}<text x="60" y="57" textAnchor="middle" className="donut-value">{total.toLocaleString()}</text><text x="60" y="72" textAnchor="middle" className="donut-label">pairs</text></svg>
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
  const [runRegistryTotal, setRunRegistryTotal] = useState(0)
  const [runRegistryLoading, setRunRegistryLoading] = useState(false)
  const [runRegistryError, setRunRegistryError] = useState('')
  const [runRegistryPage, setRunRegistryPage] = useState(1)
  const [reviews, setReviews] = useState(reviewSeed)
  const [selectedReview, setSelectedReview] = useState(null)
  const [reviewTab, setReviewTab] = useState('queue')
  const [reviewDecisionSaving, setReviewDecisionSaving] = useState(false)
  const [reviewQueueLoading, setReviewQueueLoading] = useState(false)
  const [reviewQueueError, setReviewQueueError] = useState('')
  const [reviewQueuePage, setReviewQueuePage] = useState(1)
  const [reviewQueueTotal, setReviewQueueTotal] = useState(0)
  const [reviewHistoryLoading, setReviewHistoryLoading] = useState(false)
  const [reviewHistoryError, setReviewHistoryError] = useState('')
  const [reviewHistoryPage, setReviewHistoryPage] = useState(1)
  const [reviewHistoryTotal, setReviewHistoryTotal] = useState(0)
  const [selectedReviewIds, setSelectedReviewIds] = useState(() => new Set())
  const [reviewerName, setReviewerName] = useState('')
  const [reviewReason, setReviewReason] = useState('')
  const [bulkReviewDecision, setBulkReviewDecision] = useState('MATCH')
  const [bulkReviewSaving, setBulkReviewSaving] = useState(false)
  const [datasetFilter, setDatasetFilter] = useState('All')
  const [datasetSearch, setDatasetSearch] = useState('')
  const [runFilter, setRunFilter] = useState('All')
  const [sourceTab, setSourceTab] = useState('files')
  const [models, setModels] = useState(modelSeed)
  const [modelVersions, setModelVersions] = useState([])
  const [modelPage, setModelPage] = useState(1)
  const [modelInfo, setModelInfo] = useState(null)
  const [retrainStatus, setRetrainStatus] = useState(null) // 'running' | null
  const [retrainLog, setRetrainLog] = useState('')
  const retrainOffset = useRef(0)
  const [jobDataset, setJobDataset] = useState('')
  const [jobEngine, setJobEngine] = useState('MDL-0001')
  const [jobName, setJobName] = useState('Customer deduplication · Q4')
  const [jobRunning, setJobRunning] = useState(false)
  const [jobElapsed, setJobElapsed] = useState(0)
  const [lastJob, setLastJob] = useState(null)
  const [showSourceModal, setShowSourceModal] = useState(false)
const [selectedColumns, setSelectedColumns] = useState([])
const availableComparisonColumns = [
  'first_name_std', 'last_name_std',
  'email_std', 'phone_std',
  'address_std', 'city_std', 'state_std', 'country_std',
  'dob_std', 'dob_year_std',
]
  const [showModelModal, setShowModelModal] = useState(false)
  const [connectionName, setConnectionName] = useState('Analytics PostgreSQL')
  const [modelName, setModelName] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('Not tested')
  const [sourceType, setSourceType] = useState('PostgreSQL')
  const [outputTable, setOutputTable] = useState('public.dedup_outputs')
  const [reviewSearch, setReviewSearch] = useState('')
  const [reviewDecisionFilter, setReviewDecisionFilter] = useState('REVIEW')
  const [showNotifications, setShowNotifications] = useState(false)
  const fileInputRef = useRef(null)
  const toastTimer = useRef(null)
  const databasePreviewRequest = useRef(0)
  const supabaseColumnPreviewRequest = useRef(0)
  const supabaseDataPreviewRequest = useRef(0)
  const reviewQueueRequest = useRef(0)
  const reviewHistoryRequest = useRef(0)
  const runRegistryRequest = useRef(0)
  const userNavigated = useRef(false)
  const [liveState, setLiveState] = useState('loading')
  const [liveStats, setLiveStats] = useState(null)
  const [liveModel, setLiveModel] = useState(null)
  const [liveError, setLiveError] = useState('')
  const [backendDatasets, setBackendDatasets] = useState([])
  const [selectedBackendDatasetId, setSelectedBackendDatasetId] = useState('')
  const [pairDetail, setPairDetail] = useState(null)
  const [pairDetailLoading, setPairDetailLoading] = useState(false)
  const [pairDetailError, setPairDetailError] = useState('')
  const [reviewSummary, setReviewSummary] = useState(null)
  const [backendSearchResults, setBackendSearchResults] = useState([])
  const [reviewHistory, setReviewHistory] = useState([])
  const [pairDetailRetry, setPairDetailRetry] = useState(0)
  const [databaseStatus, setDatabaseStatus] = useState(null)
  const [databaseTables, setDatabaseTables] = useState([])
  const [databaseIngestibleTables, setDatabaseIngestibleTables] = useState([])
  const [databaseIngestingTable, setDatabaseIngestingTable] = useState('')
  const [databaseColumnPreview, setDatabaseColumnPreview] = useState(null)
  const [supabaseStatus, setSupabaseStatus] = useState(null)
  const [supabaseTables, setSupabaseTables] = useState([])
  const [supabaseDatasets, setSupabaseDatasets] = useState([])
  const [supabaseRefreshing, setSupabaseRefreshing] = useState(false)
  const [supabaseColumnPreview, setSupabaseColumnPreview] = useState(null)
  const [supabaseDataPreview, setSupabaseDataPreview] = useState(null)
  const [supabaseIngestingTable, setSupabaseIngestingTable] = useState('')
  const [activityFeed, setActivityFeed] = useState([])
  const [activityTrend, setActivityTrend] = useState([])
  const [outputDestinations, setOutputDestinations] = useState([])
  const [entities, setEntities] = useState([])
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [entityMembers, setEntityMembers] = useState([])
  const [entityMembersLoading, setEntityMembersLoading] = useState(false)
  const [conflicts, setConflicts] = useState([])
  const [entityTab, setEntityTab] = useState('clusters')
  const [entitiesLoading, setEntitiesLoading] = useState(false)
  const [workspaceSettings, setWorkspaceSettings] = useState({
    workspace_name: 'HyperData Intelligence',
    timezone: 'Asia/Jakarta',
    default_landing_page: 'dashboard',
    date_format: 'DD MMM YYYY',
    theme: 'light',
    preserve_source_data: true,
    require_output_confirmation: true,
    keep_processing_audit_trail: true,
    default_output_destination: 'local_parquet',
  })
  const [mappingPreview, setMappingPreview] = useState(null)
  const [mappingOpen, setMappingOpen] = useState(false)
  const [mappingBusy, setMappingBusy] = useState(false)
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [settingsDirty, setSettingsDirty] = useState(false)
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsError, setSettingsError] = useState('')
  const [refreshTick, setRefreshTick] = useState(0)

  // Auto-refresh data every 5 seconds when on a relevant page
  useEffect(() => {
    const refreshData = async () => {
      try {
        if (activePage === 'dashboard' || activePage === 'analytics') {
          const stats = await dedupApi.getStats()
          setLiveStats(stats)
          const activity = await dedupApi.getActivityFeed(15)
          setActivityFeed(activity.activities || [])
        }
        if (activePage === 'processing' || activePage === 'history') {
          loadRuns(1, false)
        }
        if (activePage === 'models') {
          loadModelData()
          const versions = await dedupApi.getModelVersions()
          setModelVersions(versions)
        }
        if (activePage === 'review' && !selectedReview) {
          loadReviewQueue(1, false)
        }
        if (activePage === 'settings' && !settingsDirty && !settingsSaving) {
          const payload = await dedupApi.getWorkspaceSettings()
          setWorkspaceSettings(payload.settings)
        }
        if (retrainStatus === 'running') {
          const res = await dedupApi.getRetrainLog(retrainOffset.current)
          if (res.text) {
            setRetrainLog(prev => prev + res.text)
            retrainOffset.current = res.size
          }
          if (!res.running) {
            setRetrainStatus(null)
            loadModelData()
          }
        }
      } catch (e) {
        // silently ignore errors to avoid flicker
      }
    }
    const id = setInterval(refreshData, 5000)
    return () => clearInterval(id)
  }, [activePage, selectedReview, reviewDecisionFilter, retrainStatus, refreshTick, settingsDirty, settingsSaving])

  const navItem = navigation.flatMap(group => group.items).find(item => item.id === activePage)
  const meta = pageMeta[activePage]
  const visibleDatasets = useMemo(() => datasets.filter(item => (datasetFilter === 'All' || item.status === datasetFilter) && `${item.name} ${item.id} ${item.source}`.toLowerCase().includes(datasetSearch.toLowerCase())), [datasets, datasetFilter, datasetSearch])
  const visibleRuns = useMemo(() => runs.filter(run => runFilter === 'All' || run.status === runFilter), [runs, runFilter])
  const visibleReviews = useMemo(() => reviews.filter(row => `${row.id} ${row.left} ${row.right} ${row.reason}`.toLowerCase().includes(reviewSearch.toLowerCase())), [reviews, reviewSearch])
  const globalSearchResults = useMemo(() => {
    const query = globalSearch.trim().toLowerCase()
    if (!query) return []
    const pages = navigation.flatMap(group => group.items).filter(item => item.label.toLowerCase().includes(query)).map(item => ({ type: 'page', id: item.id, title: item.label, detail: 'Open workspace page' }))
    const data = datasets.filter(item => `${item.name} ${item.id}`.toLowerCase().includes(query)).slice(0, 4).map(item => ({ type: 'dataset', id: item.id, title: item.name, detail: `Dataset · ${item.status}` }))
    const history = runs.filter(item => `${item.id} ${item.dataset}`.toLowerCase().includes(query)).slice(0, 3).map(item => ({ type: 'run', id: item.id, title: item.id, detail: `Run · ${item.dataset}` }))
    const tables = databaseTables.filter(table => table.toLowerCase().includes(query)).slice(0, 3).map(table => ({ type: 'table', id: table, title: table, detail: 'Database table' }))
    return [...pages, ...data, ...history, ...tables, ...backendSearchResults].slice(0, 7)
  }, [globalSearch, datasets, runs, databaseTables, backendSearchResults])

  const flash = (message) => {
    setToast(message)
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 3600)
  }
  const navigate = (id) => {
    userNavigated.current = true
    setActivePage(id)
    setGlobalSearch('')
    setMobileMenu(false)
  }
  const loadWorkspaceSettings = async () => {
    setSettingsLoading(true)
    setSettingsError('')
    try {
      const payload = await dedupApi.getWorkspaceSettings()
      setWorkspaceSettings(payload.settings)
      setDark(payload.settings.theme === 'dark')
      if (!userNavigated.current) setActivePage(payload.settings.default_landing_page)
    } catch (error) {
      setSettingsError(error.message || 'Failed to load workspace settings')
    } finally {
      setSettingsLoading(false)
    }
  }
  const loadRuns = async (page = 1, append = false) => {
    const requestId = ++runRegistryRequest.current
    setRunRegistryLoading(true)
    setRunRegistryError('')
    if (!append) setRuns([])
    try {
      const payload = await dedupApi.getJobs(page, 50)
      if (requestId !== runRegistryRequest.current) return
      const items = (payload.jobs || []).map(job => ({
        id: job.id,
        dataset: job.dataset_name || job.dataset_id || 'Dataset unavailable',
        started: job.created_at ? new Date(job.created_at).toLocaleString() : 'Timestamp unavailable',
        duration: job.duration || '—',
        status: job.status || 'Unknown',
      }))
      setRuns(current => append ? [...current, ...items] : items)
      setRunRegistryTotal(Number(payload.total) || items.length)
      setRunRegistryPage(page)
    } catch (error) {
      if (requestId === runRegistryRequest.current) {
        setRunRegistryError(error.message || 'Failed to load job registry')
        setRuns([])
      }
    } finally {
      if (requestId === runRegistryRequest.current) setRunRegistryLoading(false)
    }
  }
  const loadReviewHistory = async (page = 1, append = false) => {
    const requestId = ++reviewHistoryRequest.current
    setReviewHistoryLoading(true)
    setReviewHistoryError('')
    if (!append) setReviewHistory([])
    try {
      const payload = await dedupApi.getReviewHistory(page, 50)
      if (requestId !== reviewHistoryRequest.current) return
      const items = payload.items || []
      setReviewHistory(current => append ? [...current, ...items] : items)
      setReviewHistoryPage(page)
      setReviewHistoryTotal(Number(payload.total) || items.length)
    } catch (error) {
      if (requestId === reviewHistoryRequest.current) {
        setReviewHistoryError(error.message || 'Failed to load review history')
        setReviewHistory([])
      }
    } finally {
      if (requestId === reviewHistoryRequest.current) setReviewHistoryLoading(false)
    }
  }
  const loadReviewQueue = async (page = 1, append = false) => {
    const requestId = ++reviewQueueRequest.current
    setReviewQueueLoading(true)
    setReviewQueueError('')
    if (!append) {
      setReviews([])
      setSelectedReview(null)
      setSelectedReviewIds(new Set())
    }
    try {
      const payload = await dedupApi.getPairs(page, 50, reviewDecisionFilter)
      if (requestId !== reviewQueueRequest.current) return
      const rows = (payload.pairs || []).map(toReviewRow)
      setReviews(current => append ? [...current, ...rows] : rows)
      setReviewQueuePage(page)
      setReviewQueueTotal(Number(payload.total) || rows.length)
      if (!append) setSelectedReview(rows[0] || null)
      return rows
    } catch (error) {
      if (requestId === reviewQueueRequest.current) {
        setReviewQueueError(error.message || 'Failed to load review queue')
        setReviews([])
        setSelectedReview(null)
      }
      return null
    } finally {
      if (requestId === reviewQueueRequest.current) setReviewQueueLoading(false)
    }
  }
  const loadLive = async () => {
    try {
      const [stats, model, datasetsResponse] = await Promise.all([
        dedupApi.getStats(),
        dedupApi.getModelInfo().catch(() => null),
        dedupApi.getDatasets().catch(() => null),
      ]);
      setLiveStats(stats);
      setLiveModel(model);
      const currentDatasets = datasetsResponse?.datasets || []
      setBackendDatasets(currentDatasets);
      setDatasets(currentDatasets.map(toDatasetRow))
      dedupApi.getReviewSummary()
        .then(setReviewSummary)
        .catch(() => setReviewSummary(null));
      dedupApi.getActivityFeed()
        .then(res => setActivityFeed(res.activities || []))
        .catch(() => setActivityFeed([]));
      dedupApi.getActivityTrend(30)
        .then(res => setActivityTrend(res.trend || []))
        .catch(() => setActivityTrend([]))
      dedupApi.getOutputDestinations()
        .then(res => setOutputDestinations(res.destinations || []))
        .catch(() => setOutputDestinations([]))
      Promise.all([
        dedupApi.getDatabaseStatus(),
        dedupApi.getDatabaseTables(),
      ]).then(([status, tables]) => {
        setDatabaseStatus(status)
        setDatabaseTables(tables.tables || [])
        setDatabaseIngestibleTables(tables.ingestible_tables || [])
      }).catch(() => {
        setDatabaseStatus({ status: 'unavailable', table_count: 0 })
        setDatabaseTables([])
        setDatabaseIngestibleTables([])
      })
      Promise.all([
        dedupApi.getSupabaseStatus().catch(() => null),
        dedupApi.getSupabaseTables().catch(() => null),
        dedupApi.getSupabaseDatasets().catch(() => null),
      ]).then(([sStatus, sTables, sDatasets]) => {
        setSupabaseStatus(sStatus || { status: 'unavailable' })
        setSupabaseTables(sTables?.tables || [])
        setSupabaseDatasets(sDatasets?.datasets || [])
      }).catch(() => {
        setSupabaseStatus({ status: 'unavailable' })
        setSupabaseTables([])
        setSupabaseDatasets([])
      })
      setLiveError("");
      setLiveState("live");
    } catch (error) {
      setLiveError(error.message || String(error));
      setLiveState("offline");
      setReviews([]);
      setSelectedReview(null);
    }
  }
  useEffect(() => {
    loadLive()
    loadWorkspaceSettings()
  }, [])
  useEffect(() => {
    if (liveState === 'live') loadRuns(1, false)
  }, [liveState])
  useEffect(() => {
    if (liveState === 'live') loadReviewQueue(1, false)
  }, [liveState, reviewDecisionFilter])
  useEffect(() => {
    if (reviewTab !== 'history') return
    loadReviewHistory(1, false)
  }, [reviewTab])
  const loadEntities = async () => {
    setEntitiesLoading(true)
    try {
      const [entitiesRes, conflictsRes] = await Promise.all([
        dedupApi.getSupabaseEntities().catch(() => ({ entities: [] })),
        dedupApi.getSupabaseConflicts().catch(() => ({ conflicts: [] })),
      ])
      const ents = entitiesRes.entities || []
      setEntities(ents)
      setConflicts(conflictsRes.conflicts || [])
      if (ents.length) {
        selectEntity(ents[0])
      }
    } catch (e) {
      flash(`Failed to load entities: ${e.message || e}`)
    } finally {
      setEntitiesLoading(false)
    }
  }
  const selectEntity = async (entity) => {
    setSelectedEntity(entity)
    setEntityMembersLoading(true)
    try {
      const res = await dedupApi.getSupabaseEntityMembers(entity.entity_id)
      setEntityMembers(res.members || [])
    } catch (e) {
      setEntityMembers([])
    } finally {
      setEntityMembersLoading(false)
    }
  }
  useEffect(() => {
    if (activePage === 'entities' && liveState === 'live') {
      loadEntities()
    }
  }, [activePage, liveState])
  const loadModelData = async () => {
    try {
      const [versionsRes, infoRes] = await Promise.all([
        dedupApi.getModelVersions().catch(() => []),
        dedupApi.getModelInfo().catch(() => null),
      ])
      const versions = Array.isArray(versionsRes) ? versionsRes : []
      const sorted = [...versions].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
      setModelVersions(sorted)
      setModelInfo(infoRes || null)
    } catch (e) {
      flash(`Failed to load model data: ${e.message || e}`)
    }
  }
  useEffect(() => {
    if (activePage === 'models') loadModelData()
  }, [activePage])
  useEffect(() => {
    const query = globalSearch.trim()
    if (!query) {
      setBackendSearchResults([])
      return
    }
    let cancelled = false
    const timeout = window.setTimeout(() => {
      dedupApi.search(query)
        .then(payload => {
          if (!cancelled) {
            setBackendSearchResults((payload.results || []).slice(0, 5).map(pair => ({
              type: 'pair',
              id: `${pair.record_id_l}__${pair.record_id_r}`,
              title: `${pair.record_id_l} ↔ ${pair.record_id_r}`,
              detail: `${pair.decision} · ${Number(pair.match_probability).toFixed(4)}`,
            })))
          }
        })
        .catch(() => {
          if (!cancelled) setBackendSearchResults([])
        })
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [globalSearch])
  useEffect(() => {
    if (!selectedReview?.id) {
      setPairDetail(null)
      setPairDetailError('')
      setPairDetailLoading(false)
      return
    }
    if (!selectedReview.id.includes('__')) {
      setPairDetail(null)
      setPairDetailError('')
      setPairDetailLoading(false)
      return
    }
    const [id1, id2] = selectedReview.id.split('__')
    let cancelled = false
    setPairDetailLoading(true)
    setPairDetail(null)
    setPairDetailError('')
    dedupApi.getPairDetail(id1, id2)
      .then(detail => {
        if (!cancelled) setPairDetail(detail)
      })
      .catch(error => {
        if (!cancelled) setPairDetailError(error.message || 'Failed to load pair detail')
      })
      .finally(() => {
        if (!cancelled) setPairDetailLoading(false)
      })
    return () => { cancelled = true }
  }, [selectedReview?.id, pairDetailRetry])
  const selectFile = async (file) => {
    if (!file) return
    setMappingBusy(true)
    try {
      const preview = await dedupApi.inspectUpload(file)
      setMappingPreview({ file, columns: preview.columns || [], targets: preview.targets || [], mapping: preview.suggested_mapping || {}, rows: preview.rows || 0 })
      setMappingOpen(true)
    } catch (error) {
      flash(`Gagal membaca kolom file: ${error.message || error}`)
    } finally {
      setMappingBusy(false)
    }
  }
  const confirmMapping = async () => {
    if (!mappingPreview) return
    setMappingBusy(true)
    try {
      const uploaded = await dedupApi.uploadDataset(mappingPreview.file, mappingPreview.mapping)
      setBackendDatasets(current => [uploaded.dataset, ...current])
      setSelectedBackendDatasetId(uploaded.dataset.id)
      setDatasets(current => [toDatasetRow(uploaded.dataset), ...current.filter(item => item.id !== uploaded.dataset.id)])
      setMappingOpen(false)
      setMappingPreview(null)
      flash(`${mappingPreview.file.name} uploaded and validated by FastAPI.`)
    } catch (error) {
      flash(`Gagal mengunggah dataset: ${error.message || error}`)
    } finally {
      setMappingBusy(false)
    }
  }
  const importDatabaseTable = async (table) => {
    setDatabaseIngestingTable(table)
    try {
      const result = await dedupApi.ingestDatabaseTable(table)
      if (result.status === 'empty') {
        flash(`Table ${table} contains no rows; no dataset was created.`)
        return
      }
      if (result.status !== 'ingested' || !result.dataset) {
        throw new Error('The API did not return a dataset.')
      }
      setBackendDatasets(current => [result.dataset, ...current.filter(item => item.id !== result.dataset.id)])
      setDatasets(current => [toDatasetRow(result.dataset), ...current.filter(item => item.id !== result.dataset.id)])
      setSelectedBackendDatasetId(result.dataset.id)
      flash(`${table} imported as dataset ${result.dataset.id}.`)
    } catch (error) {
      flash(`Database import failed: ${error.message || error}`)
    } finally {
      setDatabaseIngestingTable('')
    }
  }
  const importSupabaseTable = async (table) => {
    setSupabaseIngestingTable(table)
    try {
      const result = await dedupApi.ingestSupabaseTable(table)
      if (result.status === 'empty') {
        flash(`Table ${table} contains no rows; no dataset was created.`)
        return
      }
      if (result.status !== 'ingested' || !result.dataset) {
        throw new Error('The API did not return a dataset.')
      }
      setBackendDatasets(current => [result.dataset, ...current.filter(item => item.id !== result.dataset.id)])
      setDatasets(current => [toDatasetRow(result.dataset), ...current.filter(item => item.id !== result.dataset.id)])
      setSelectedBackendDatasetId(result.dataset.id)
      flash(`${table} (Supabase) imported as dataset ${result.dataset.id}.`)
    } catch (error) {
      flash(`Supabase import failed: ${error.message || error}`)
    } finally {
      setSupabaseIngestingTable('')
    }
  }
  const toggleDatabaseColumnPreview = async (table) => {
    if (databaseColumnPreview?.table === table && !databaseColumnPreview.loading) {
      databasePreviewRequest.current += 1
      setDatabaseColumnPreview(null)
      return
    }
    const requestId = databasePreviewRequest.current + 1
    databasePreviewRequest.current = requestId
    setDatabaseColumnPreview({ table, loading: true, error: '', columns: [] })
    try {
      const result = await dedupApi.getDatabaseTableColumns(table)
      if (databasePreviewRequest.current === requestId) {
        setDatabaseColumnPreview({ table, loading: false, error: '', columns: result.columns || [] })
      }
    } catch (error) {
      if (databasePreviewRequest.current === requestId) {
        setDatabaseColumnPreview({
          table,
          loading: false,
          error: error.message || 'Failed to load table columns',
          columns: [],
        })
      }
    }
  }

  const toggleSupabaseColumnPreview = async (table) => {
    if (supabaseColumnPreview?.table === table && !supabaseColumnPreview.loading) {
      supabaseColumnPreviewRequest.current += 1
      setSupabaseColumnPreview(null)
      return
    }
    const requestId = ++supabaseColumnPreviewRequest.current
    setSupabaseColumnPreview({ table, loading: true, error: '', columns: [] })
    try {
      const result = await dedupApi.getSupabaseTableColumns(table)
      if (supabaseColumnPreviewRequest.current === requestId) {
        setSupabaseColumnPreview({ table, loading: false, error: '', columns: result.columns || [] })
      }
    } catch (error) {
      if (supabaseColumnPreviewRequest.current === requestId) {
        setSupabaseColumnPreview({
          table,
          loading: false,
          error: error.message || 'Failed to load table columns',
          columns: [],
        })
      }
    }
  }

  const toggleSupabaseDataPreview = async (table) => {
    if (supabaseDataPreview?.table === table && !supabaseDataPreview.loading) {
      supabaseDataPreviewRequest.current += 1
      setSupabaseDataPreview(null)
      return
    }
    const requestId = ++supabaseDataPreviewRequest.current
    setSupabaseDataPreview({ table, loading: true, error: '', columns: [], rows: [] })
    try {
      const result = await dedupApi.getSupabaseTablePreview(table, 15)
      if (supabaseDataPreviewRequest.current === requestId) {
        setSupabaseDataPreview({
          table,
          loading: false,
          error: '',
          columns: result.columns || [],
          rows: result.rows || [],
          total: result.total_previewed || 0,
        })
      }
    } catch (error) {
      if (supabaseDataPreviewRequest.current === requestId) {
        setSupabaseDataPreview({
          table,
          loading: false,
          error: error.message || 'Failed to load table preview data',
          columns: [],
          rows: [],
        })
      }
    }
  }
  const runPipeline = async () => {
    if (!selectedBackendDatasetId) return flash('Upload and select a validated backend dataset first.')
    if (!jobEngine) return flash('Choose a processing engine first.')
    if (jobRunning) return
    if (!window.confirm("Submit a processing request for the selected dataset?")) return
    setJobRunning(true)
    setJobElapsed(0)
    setLastJob(null)
    const startedAt = Date.now()
    // create_job is synchronous: it blocks until the run finishes, so show
    // elapsed time while it runs instead of a fake percentage.
    const timer = setInterval(() => setJobElapsed(Math.round((Date.now() - startedAt) / 1000)), 500)
    try {
      const response = await dedupApi.createJob({ dataset_id: selectedBackendDatasetId, selected_columns: selectedColumns.length > 0 ? selectedColumns : undefined })
      if (!response?.job?.id) {
        throw new Error('The backend did not confirm that a processing job was created.')
      }
      setLastJob(response.job)
      flash(`Processing run ${response.job.id} completed! Scored ${response.job.pairs_scored || 0} pairs in ${response.job.duration || '—'}.`)
      await loadRuns(1, false)
      await loadReviewQueue(1, false)
      try {
        setLiveStats(await dedupApi.getStats())
      } catch (err) {}
    } catch (error) {
      flash(`Gagal menjalankan dedup: ${error.message || error}`)
    } finally {
      clearInterval(timer)
      setJobRunning(false)
    }
  }
  const decideReview = async (decision) => {
    if (!selectedReview || reviewDecisionSaving) return
    if (liveState !== 'live') {
      flash('Review decisions require a live backend connection.')
      return
    }
    if (pairDetailLoading || pairDetailError || !pairDetail) {
      flash('Wait for the pair details to load before saving a decision.')
      return
    }
    if (!reviewerName.trim()) {
      flash('Enter your reviewer name before saving a decision.')
      return
    }
    if (decision !== 'REVIEW' && !reviewReason.trim()) {
      flash('Enter a reason for MATCH or NON_MATCH decisions.')
      return
    }
    const [id1, id2] = selectedReview.id.split('__')
    if (!id1 || !id2) {
      flash('This pair has an invalid identifier and cannot be reviewed.')
      return
    }
    if (!window.confirm(`Save ${decision} for ${selectedReview.id}?`)) return
    const selectedId = selectedReview.id
    setReviewDecisionSaving(true)
    try {
      const result = await dedupApi.submitReviewDecision(
        id1,
        id2,
        decision,
        'full',
        reviewerName.trim(),
        reviewReason.trim(),
      )
      if (!['saved', 'duplicate'].includes(result?.status)) {
        throw new Error('The backend did not confirm the review decision.')
      }
      if (result.status === 'saved') {
        setSelectedReview(current => current?.id === selectedId ? { ...current, decision } : current)
        setReviews(current => current.map(item => item.id === selectedId ? { ...item, decision } : item))
        flash(`Decision ${decision} saved to the review audit.`)
      } else {
        flash('This review request was already saved.')
      }
      await loadReviewQueue(1, false)
      try {
        setLiveStats(await dedupApi.getStats())
      } catch (error) {
        flash(`Decision saved, but stats could not be refreshed: ${error.message || error}`)
      }
    } catch (error) {
      flash(`Could not save review decision: ${error.message || error}`)
    } finally {
      setReviewDecisionSaving(false)
    }
  }
  const submitBulkReview = async () => {
    const pairIds = Array.from(selectedReviewIds)
    if (!pairIds.length || bulkReviewSaving) return
    if (pairIds.length > 100) {
      flash('Bulk review is limited to 100 pairs at a time.')
      return
    }
    if (liveState !== 'live') {
      flash('Bulk review requires a live backend connection.')
      return
    }
    if (!reviewerName.trim()) {
      flash('Enter your reviewer name before applying bulk decisions.')
      return
    }
    if (bulkReviewDecision !== 'REVIEW' && !reviewReason.trim()) {
      flash('Enter a reason for MATCH or NON_MATCH decisions.')
      return
    }
    if (!window.confirm(`Apply ${bulkReviewDecision} to ${pairIds.length} selected pairs?`)) return
    setBulkReviewSaving(true)
    try {
      const response = await dedupApi.submitBulkReview(
        pairIds,
        bulkReviewDecision,
        reviewerName.trim(),
        reviewReason.trim(),
      )
      const results = response.results || []
      const saved = results.filter(result => result.status === 'saved').length
      const duplicates = results.filter(result => result.status === 'duplicate').length
      const failed = pairIds.length - saved - duplicates
      const remainingIds = results
        .filter(result => !['saved', 'duplicate'].includes(result.status))
        .map(result => result.pair_id)
      flash(`Bulk review: ${saved} saved, ${duplicates} already saved, ${failed} failed.`)
      await loadReviewQueue(1, false)
      setSelectedReviewIds(new Set(remainingIds))
      try {
        setLiveStats(await dedupApi.getStats())
      } catch (error) {
        flash(`Bulk review completed, but stats could not be refreshed: ${error.message || error}`)
      }
    } catch (error) {
      flash(`Bulk review failed: ${error.message || error}`)
    } finally {
      setBulkReviewSaving(false)
    }
  }
  const saveWorkspaceSettings = async () => {
    setSettingsSaving(true)
    setSettingsError('')
    try {
      const payload = await dedupApi.saveWorkspaceSettings(workspaceSettings)
      setWorkspaceSettings(payload.settings)
      setDark(payload.settings.theme === 'dark')
      flash('Workspace settings saved on the backend.')
    } catch (error) {
      setSettingsError(error.message || 'Failed to save workspace settings')
      flash(`Could not save workspace settings: ${error.message || error}`)
    } finally {
      setSettingsSaving(false)
    }
  }
  const setWorkspaceSetting = (key, value) => {
    setWorkspaceSettings(current => ({ ...current, [key]: value }))
  }
  const exportReviews = () => {
    const rows = [['pair_id', 'left_record', 'right_record', 'score', 'decision', 'evidence'], ...reviews.map(row => [row.id, row.left, row.right, row.score, row.decision, row.reason])]
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'nexus-loaded-review-pairs.csv'
    link.click()
    URL.revokeObjectURL(url)
    flash(`Exported ${reviews.length} loaded review pairs.`)
  }
  const exportDatasets = () => {
    if (!visibleDatasets.length) {
      flash('There are no datasets to export.')
      return
    }
    const rows = [
      ['id', 'name', 'source', 'rows', 'columns', 'size', 'status', 'updated'],
      ...visibleDatasets.map(d => [d.id, d.name, d.source, d.rows, d.columns, d.size, d.status, d.updated]),
    ]
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'nexus-dataset-inventory.csv'
    link.click()
    URL.revokeObjectURL(url)
    flash(`Exported ${visibleDatasets.length} datasets.`)
  }
  const exportRunHistory = () => {
    if (!runs.length) {
      flash('There are no loaded run records to export.')
      return
    }
    const rows = [
      ['run_id', 'dataset', 'status', 'started'],
      ...runs.map(run => [run.id, run.dataset, run.status, run.started]),
    ]
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'nexus-loaded-run-history.csv'
    link.click()
    URL.revokeObjectURL(url)
    flash(`Exported ${runs.length} loaded run records.`)
  }
  const exportDashboardStats = () => {
    if (!liveStats) {
      flash('Dashboard data is unavailable. Export requires a live backend.')
      return
    }
    const rows = [
      ['metric', 'value'],
      ['total_pairs', liveStats.total_pairs],
      ['matches', liveStats.matches],
      ['review', liveStats.review],
      ['non_matches', liveStats.non_matches],
      ['avg_probability', liveStats.avg_probability],
      ['timestamp', liveStats.timestamp],
    ]
    const csv = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'nexus-dashboard-stats.csv'
    link.click()
    URL.revokeObjectURL(url)
    flash('Live dashboard stats exported.')
  }
  const addModel = () => {
    if (!modelName.trim()) return
    const id = `MDL-${String(models.length + 1).padStart(4, '0')}`
    setModels(current => [...current, { id, name: modelName.trim(), family: 'Custom processing engine', version: 'Unversioned', runtime: 'Adapter not connected', status: 'Planned', description: 'Local registry placeholder. Add a backend adapter before execution.' }])
    setModelName('')
    setShowModelModal(false)
    flash('Model placeholder added to the local registry.')
  }

  const renderDashboard = () => {
    const distribution = liveStats
      ? [liveStats.matches, liveStats.review, liveStats.non_matches]
      : []
    const distributionTotal = liveStats?.total_pairs || 0
    const percentage = value => distributionTotal
      ? `${((value / distributionTotal) * 100).toFixed(1)}%`
      : '—'
    return <>
      <PageHeader title={meta[0]} subtitle={meta[1]} actions={<><div className="date-control"><CalendarDays size={15}/>{formatDate(workspaceSettings.date_format, workspaceSettings.timezone)} <ChevronDown size={13}/></div><Button icon={Download} onClick={exportDashboardStats}>Export report</Button></>} />
      <div className="welcome-strip"><div className="welcome-symbol"><Sparkles size={20}/></div><div><b>{liveState === 'live' ? 'Live data from FastAPI' : liveState === 'offline' ? 'Backend unavailable' : 'Connecting to FastAPI…'}</b><p>{liveState === 'live' ? 'Overview KPIs come from /api/stats and /api/model/info.' : liveState === 'offline' ? `Backend connection failed: ${liveError}. Live dashboard data is unavailable.` : 'Waiting for the backend response.'}</p></div><span className="demo-badge">{liveState === 'live' ? 'LIVE' : liveState === 'offline' ? 'OFFLINE' : 'CONNECTING'}</span></div>
      <div className="metrics-grid">
        <MetricCard label="Pairs scored" value={liveStats ? liveStats.total_pairs.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : 'OFFLINE'} caption="from /api/stats" icon={Layers3} tone="blue" />
        <MetricCard label="Matches" value={liveStats ? liveStats.matches.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : '—'} caption="match_threshold" icon={Workflow} tone="violet" />
        <MetricCard label="Awaiting review" value={liveStats ? liveStats.review.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : '—'} caption="review queue" icon={ListChecks} tone="amber" trend="down" />
        <MetricCard label="Non-matches" value={liveStats ? liveStats.non_matches.toLocaleString() : '—'} change={liveState === 'live' ? 'LIVE' : '—'} caption="from /api/stats" icon={CheckCheck} tone="mint" />
      </div>
      <div className="dashboard-grid">
        <Card className="chart-card">
          <div className="card-header"><div><h3>Processing activity</h3><p>Daily processed records from /api/activity/trend</p></div></div>
          {(() => {
            const active = activityTrend.filter(day => day.processed || day.runs || day.reviews)
            const max = Math.max(...activityTrend.map(day => day.processed), 1)
            if (!activityTrend.length || !active.length) {
              return <div className="empty-state small-empty"><CircleAlert size={20}/><b>Activity trend unavailable</b><span>No processing activity recorded in the last 30 days.</span></div>
            }
            return <div className="activity-chart" role="img" aria-label="Daily processed records for the last 30 days">
              {activityTrend.map(day => (
                <span key={day.date} title={`${day.date}: ${day.processed} records · ${day.runs} runs · ${day.reviews} reviews`}
                  style={{ height: `${Math.max((day.processed / max) * 100, 2)}%`, background: day.processed ? '#31a889' : '#e9edf4' }} />
              ))}
            </div>
          })()}
        </Card>
        <Card className="distribution-card">
          <div className="card-header"><div><h3>Decision distribution</h3><p>{liveStats ? 'Current prediction decision counts' : 'Live prediction data required'}</p></div><button className="icon-button" aria-label="Open evaluation" onClick={() => navigate('analytics')}><ArrowRight size={16}/></button></div>
          {distributionTotal > 0 ? (
            <div className="donut-wrap">
              <Donut segments={distribution} total={distributionTotal}/>
              <div className="donut-legend">
                <div><i className="green"/><span>Matched</span><b>{percentage(distribution[0])}</b></div>
                <div><i className="amber"/><span>Review</span><b>{percentage(distribution[1])}</b></div>
                <div><i className="grey"/><span>Non-match</span><b>{percentage(distribution[2])}</b></div>
              </div>
            </div>
          ) : <div className="empty-state small-empty"><SearchX size={20}/><b>Distribution unavailable</b><span>Load prediction data from FastAPI to see decision counts.</span></div>}
          <div className="distribution-note"><CircleAlert size={14}/> Counts reflect current predictions, not independently validated model quality.</div>
        </Card>
        <Card className="runs-card">
          <div className="card-header"><div><h3>Recent processing runs</h3><p>Backend job registry</p></div><button className="text-link" onClick={() => navigate('history')}>View all <ArrowRight size={14}/></button></div>
          <div className="compact-run-list">
            {runs.slice(0, 4).map(run => <div className="compact-run" key={run.id}><div className="run-symbol"><Workflow size={16}/></div><div className="compact-run-main"><b>{run.id} <span>· {run.dataset}</span></b><small>{run.started}</small></div><StatusPill value={run.status}/></div>)}
            {runs.length === 0 && <div className="empty-state small-empty"><SearchX size={20}/><b>No processing runs</b><span>The backend job registry has no recorded runs.</span></div>}
          </div>
        </Card>
        <Card className="activity-card">
          <div className="card-header"><div><h3>Workspace activity</h3><p>Audit-backed events</p></div></div>
          <div className="activity-list">{activityFeed.length ? activityFeed.map((item, index) => {
            const Icon = item.icon || (item.type === 'review' ? ListChecks : (item.type === 'dataset' ? Table2 : Workflow))
            const formattedTime = item.time ? new Date(item.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'
            return <div className="activity-item" key={index}><span className={`activity-symbol ${item.tone}`}><Icon size={15}/></span><div><b>{item.title}</b><p>{item.detail}</p></div><small>{formattedTime}</small></div>
          }) : <div className="empty-state small-empty"><SearchX size={20}/><b>No activity events</b><span>No audit events recorded yet.</span></div>}</div>
        </Card>
      </div>
      <div className="bottom-grid"><Card className="quick-card"><div className="card-header"><div><h3>Quick actions</h3><p>Start a common data task</p></div></div><div className="quick-actions"><button onClick={() => navigate('sources')}><span className="quick-icon blue"><CloudUpload size={18}/></span><b>Import data</b><small>Upload a file or connect a source</small><ArrowRight size={16}/></button><button onClick={() => navigate('processing')}><span className="quick-icon violet"><Play size={18}/></span><b>New processing run</b><small>Configure and execute a pipeline</small><ArrowRight size={16}/></button><button onClick={() => navigate('review')}><span className="quick-icon amber"><ListChecks size={18}/></span><b>Review matches</b><small>Resolve uncertain record pairs</small><ArrowRight size={16}/></button></div></Card><Card className="engine-card"><div className="engine-head"><span className="engine-icon"><BrainCircuit size={19}/></span><span className="engine-state"><i/> Integration planned</span></div><h3>Splink CRM Linkage</h3><p>First processing engine planned from the existing deduplication repository.</p><div className="engine-meta"><span>Runtime <b>Python · DuckDB</b></span><span>Adapter <b>Pending</b></span></div><button className="text-link" onClick={() => navigate('models')}>View model registry <ArrowRight size={14}/></button></Card></div>
    </>
  }

  const renderSources = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => setShowSourceModal(true)}
          >
            Add connection
          </Button>
        }
      />
      <div className="source-summary-grid">
        <MetricCard
          label="Registered sources"
          value={String(backendDatasets.length).padStart(2, "0")}
          change="Backend"
          caption="uploaded datasets"
          icon={Database}
          tone="blue"
        />
        <MetricCard
          label="Healthy connections"
          value={databaseStatus?.status === "connected" ? "01 / 01" : "—"}
          change={databaseStatus?.status === "connected" ? "Connected" : "Unavailable"}
          caption={databaseStatus?.status === "connected" ? "splink_data read-only" : "database not connected"}
          icon={ShieldCheck}
          tone="mint"
        />
        <MetricCard
          label="Imported datasets"
          value={String(datasets.length).padStart(2, "0")}
          change="Backend"
          caption="registered datasets"
          icon={FileSpreadsheet}
          tone="violet"
        />
      </div>
      <Card className="source-tabs-card">
        <div className="tab-row">
          <button
            className={sourceTab === "files" ? "selected" : ""}
            onClick={() => setSourceTab("files")}
          >
            <FileSpreadsheet size={16} /> File sources
          </button>
          <button
            className={sourceTab === "database" ? "selected" : ""}
            onClick={() => setSourceTab("database")}
          >
            <Database size={16} /> Database connections
          </button>
        </div>
        {sourceTab === "files" ? (
          <div className="source-content">
            <div className="upload-panel">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.parquet"
                hidden
                onChange={(event) => {
                  selectFile(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
              <div className="upload-illustration">
                <CloudUpload size={25} />
              </div>
              <h3>Bring your data into the workspace</h3>
              <p>
                Choose a local file to register it as a dataset in this
                prototype.
              </p>
              <Button
                variant="primary"
                icon={CloudUpload}
                onClick={() => fileInputRef.current?.click()}
              >
                Choose a file
              </Button>
              <small>
                CSV or Parquet · Columns mapped before the upload is registered
              </small>
            </div>
            <div className="source-guidance">
              <div>
                <span className="guidance-icon blue">
                  <FileSpreadsheet size={17} />
                </span>
                <div>
                  <b>CSV / tabular files</b>
                  <p>
                    Best for structured customer, transaction, and reference
                    data.
                  </p>
                </div>
              </div>
              <div>
                <span className="guidance-icon violet">
                  <HardDrive size={17} />
                </span>
                <div>
                  <b>Parquet files</b>
                  <p>Columnar format for efficient analytical workflows.</p>
                </div>
              </div>
              <div>
                <span className="guidance-icon amber">
                  <ShieldCheck size={17} />
                </span>
                <div>
                  <b>Validation before processing</b>
                  <p>
                    Check required columns, types, nulls, and mapping before a
                    run.
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="connections-list">
            <div className="connection-card">
              <div className="connection-brand">
                <Database size={21} />
              </div>
              <div className="connection-info">
                <div>
                  <h3>Analytics PostgreSQL</h3>
                  <StatusPill value={connectionStatus} />
                </div>
                <p>localhost:5432 · analytics · Read-only source</p>
                <small>
                  Last checked:{" "}
                  {connectionStatus === "Demo checked"
                    ? "Just now (demo only)"
                    : "Not checked"}
                </small>
              </div>
              <div className="connection-actions">
                <Button
                  onClick={() => {
                    setConnectionStatus("Demo checked");
                    flash(
                      "Demo connection check completed locally. No real database connection was attempted.",
                    );
                  }}
                  icon={RefreshCw}
                >
                  Test connection
                </Button>
                <Button
                  variant="ghost"
                  icon={MoreHorizontal}
                  onClick={() =>
                    flash(
                      "Connection management is not connected to a backend.",
                    )
                  }
                />
              </div>
            </div>
            <div className="connection-card muted-card">
              <div className="connection-brand faded">
                <Database size={21} />
              </div>
              <div className="connection-info">
                <div>
                  <h3>Staging PostgreSQL</h3>
                  <StatusPill value="Not configured" />
                </div>
                <p>Connection details have not been provided.</p>
                <small>
                  Configure credentials securely in the backend environment.
                </small>
              </div>
              <Button onClick={() => setShowSourceModal(true)} icon={Plus}>
                Configure
              </Button>
            </div>
          </div>
        )}
      </Card>
      <Card className="table-card">
        <div className="card-header">
          <div>
            <h3>Recently imported datasets</h3>
            <p>Files and tables registered in this workspace</p>
          </div>
          <button className="text-link" onClick={() => navigate("datasets")}>
            Open datasets <ArrowRight size={14} />
          </button>
        </div>
        <Table
          columns={[
            {
              key: "name",
              label: "Dataset",
              render: (r) => (
                <div className="dataset-name">
                  <FileSpreadsheet size={16} />
                  <div>
                    <b>{r.name}</b>
                    <small>{r.id}</small>
                  </div>
                </div>
              ),
            },
            { key: "source", label: "Source" },
            { key: "rows", label: "Rows" },
            {
              key: "status",
              label: "Status",
              render: (r) => <StatusPill value={r.status} />,
            },
            { key: "updated", label: "Last updated" },
          ]}
          rows={datasets.slice(0, 4)}
        />
      </Card>
    </>
  );

  const renderDatasets = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={
          <>
            <Button icon={RefreshCw} onClick={() => loadLive()}>
              Refresh
            </Button>
            <Button
              variant="primary"
              icon={Plus}
              onClick={() => navigate("sources")}
            >
              Import dataset
            </Button>
          </>
        }
      />
      <div className="metrics-grid compact-metrics">
        <MetricCard
          label="Total datasets"
          value={String(datasets.length).padStart(2, "0")}
          change="+1"
          caption="in current workspace"
          icon={Table2}
          tone="blue"
        />
        <MetricCard
          label="Validated"
          value={String(
            datasets.filter((row) => row.status === "Validated").length,
          ).padStart(2, "0")}
          change="Ready"
          caption="for pipeline execution"
          icon={CheckCircle2}
          tone="mint"
        />
        <MetricCard
          label="Needs attention"
          value={String(
            datasets.filter((row) => row.status !== "Validated").length,
          ).padStart(2, "0")}
          change="Action"
          caption="mapping or validation"
          icon={AlertTriangle}
          tone="amber"
        />
      </div>
      <Card className="table-card">
        <div className="table-toolbar">
          <div className="search-field">
            <Search size={15} />
            <input
              value={datasetSearch}
              onChange={(event) => setDatasetSearch(event.target.value)}
              placeholder="Search datasets..."
            />
          </div>
          <div className="toolbar-right">
            <div className="select-wrap">
              <Filter size={14} />
              <select
                value={datasetFilter}
                onChange={(event) => setDatasetFilter(event.target.value)}
              >
                <option>All</option>
                <option>Validated</option>
                <option>Needs mapping</option>
                <option>Draft</option>
              </select>
            </div>
            <Button icon={Download} onClick={exportDatasets}>
              Export list
            </Button>
          </div>
        </div>
        <Table
          columns={[
            {
              key: "name",
              label: "Dataset name",
              render: (r) => (
                <div className="dataset-name">
                  <span className="file-type-icon">
                    <FileSpreadsheet size={16} />
                  </span>
                  <div>
                    <b>{r.name}</b>
                    <small>{r.id}</small>
                  </div>
                </div>
              ),
            },
            { key: "source", label: "Source" },
            { key: "rows", label: "Records", className: "numeric" },
            { key: "columns", label: "Columns", className: "numeric" },
            { key: "size", label: "Size" },
            {
              key: "status",
              label: "Validation",
              render: (r) => <StatusPill value={r.status} />,
            },
            { key: "updated", label: "Updated" },
            {
              key: "action",
              label: "",
              render: (r) => (
                <button
                  className="row-action"
                  aria-label={`Detail dataset ${r.name}`}
                  onClick={() =>
                    flash(`${r.name}: dataset detail panel is planned.`)
                  }
                >
                  <MoreHorizontal size={17} />
                </button>
              ),
            },
          ]}
          rows={visibleDatasets}
        />
        <div className="table-footer">
          <span>
            Showing {visibleDatasets.length} of {datasets.length} datasets
          </span>
          <div>
            <button disabled aria-label="Previous page">
              <ChevronLeft size={14} />
            </button>
            <button className="current" aria-label="Page 1">1</button>
            <button disabled aria-label="Next page">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </Card>
      <div className="info-banner">
        <ShieldCheck size={17} />
        <div>
          <b>Validation is separate from processing</b>
          <p>
            Only validated datasets should be selectable for a production run.
            Column mapping and source schema checks will be handled by the
            backend.
          </p>
        </div>
      </div>
    </>
  );

  const renderProcessing = () => {
    const steps = ['Schema validation', 'Record ID generation', 'Standardization', 'Blocking', 'Probabilistic scoring', 'Decision & review outputs', 'Clustering & master record']
    const descriptions = ['Check required fields and data types', 'Create an internal identifier for each row', 'Normalize configured attributes', 'Generate candidate record pairs', 'Calculate linkage probabilities with the selected engine', 'Assign MATCH / REVIEW / NON_MATCH decisions', 'Build entity groups and master records']
    return (
      <>
        <PageHeader
          title={meta[0]}
          subtitle={meta[1]}
          actions={
            <div className="draft-label">
              <span /> Backend dataset required
            </div>
          }
        />
        <div className="processing-layout">
          <div className="processing-main">
            <Card className="config-card">
              <div className="section-title">
                <div>
                  <span className="section-kicker">01 / INPUT</span>
                  <h3>Choose your data</h3>
                  <p>Select a dataset uploaded and validated by FastAPI.</p>
                </div>
                <span className="step-status">Required</span>
              </div>
              <div className="form-grid">
                <Field
                  label="Backend dataset"
                  hint="Seed datasets are not executable."
                >
                  <select
                    value={selectedBackendDatasetId}
                    onChange={(event) =>
                      setSelectedBackendDatasetId(event.target.value)
                    }
                  >
                    <option value="">Select an uploaded dataset</option>
                    {backendDatasets.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · {item.rows} rows · {item.status}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Run name">
                  <input
                    value={jobName}
                    onChange={(event) => setJobName(event.target.value)}
                    placeholder="Give this run a name"
                  />
                </Field>
              </div>

              <div className="column-picker">
                <div className="column-picker-head">
                  <div>
                    <span className="column-picker-title">
                      Comparison columns
                    </span>
                    <small>
                      Pilih kolom standar untuk pembanding ·{" "}
                      {selectedColumns.length}/
                      {availableComparisonColumns.length} dipilih
                    </small>
                  </div>
                  <div className="column-picker-actions">
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedColumns([...availableComparisonColumns])
                      }
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedColumns([])}
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="column-selector">
                  {availableComparisonColumns.map((col) => {
                    const checked = selectedColumns.includes(col);
                    return (
                      <label
                        key={col}
                        className={`column-chip ${checked ? "is-checked" : ""}`}
                      >
                        <input
                          type="checkbox"
                          className="checkbox-input"
                          checked={checked}
                          value={col}
                          onChange={() =>
                            setSelectedColumns((prev) =>
                              prev.includes(col)
                                ? prev.filter((c) => c !== col)
                                : [...prev, col],
                            )
                          }
                        />
                        <span className="checkbox-box" aria-hidden="true" />
                        <span className="column-chip-text">{col}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="selected-source">
                <span className="file-type-icon">
                  <FileSpreadsheet size={17} />
                </span>
                <div>
                  <b>
                    {backendDatasets.find(
                      (item) => item.id === selectedBackendDatasetId,
                    )?.name || "No backend dataset selected"}
                  </b>
                  <small>
                    {backendDatasets.find(
                      (item) => item.id === selectedBackendDatasetId,
                    )?.rows || "—"}{" "}
                    records ·{" "}
                    {backendDatasets.find(
                      (item) => item.id === selectedBackendDatasetId,
                    )?.columns || "—"}{" "}
                    columns · Backend dataset
                  </small>
                </div>
                <StatusPill
                  value={selectedBackendDatasetId ? "Validated" : "Required"}
                />
              </div>
            </Card>
            <Card className="config-card">
              <div className="section-title">
                <div>
                  <span className="section-kicker">02 / ENGINE</span>
                  <h3>Select a processing engine</h3>
                  <p>
                    Model-specific settings are isolated from the shared
                    platform workflow.
                  </p>
                </div>
                <button
                  className="text-link"
                  onClick={() => navigate("models")}
                >
                  Manage registry <ArrowRight size={14} />
                </button>
              </div>
              <div className="engine-select-list">
                {models.map((model) => (
                  <button
                    key={model.id}
                    className={cx(
                      "engine-select",
                      jobEngine === model.id && "selected",
                    )}
                    onClick={() => setJobEngine(model.id)}
                  >
                    <span className="engine-select-icon">
                      <BrainCircuit size={18} />
                    </span>
                    <span className="engine-select-text">
                      <b>{model.name}</b>
                      <small>
                        {model.family} · {model.runtime}
                      </small>
                    </span>
                    <span className="engine-select-state">
                      <StatusPill value={model.status} />
                      {jobEngine === model.id && <CheckCircle2 size={17} />}
                    </span>
                  </button>
                ))}
              </div>
              <div className="info-banner compact">
                <Sparkles size={16} />
                <div>
                  <b>Engine Ready</b>
                  <p>
                    Selected dataset (uploaded file or Supabase ingestion) will
                    be standardized and linked using Splink with DuckDB engine.
                  </p>
                </div>
              </div>
            </Card>
            <Card className="config-card">
              <div className="section-title">
                <div>
                  <span className="section-kicker">03 / PIPELINE</span>
                  <h3>Processing stages</h3>
                  <p>
                    Stages reflect the fixed deduplication workflow executed by
                    the backend.
                  </p>
                </div>
              </div>
              <div className="pipeline-list">
                {steps.map((step, index) => (
                  <div className="pipeline-row" key={step}>
                    <span className="pipeline-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <b>{step}</b>
                      <small>{descriptions[index]}</small>
                    </div>
                    <span className="pipeline-state">Unavailable</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
          <aside className="processing-side">
            <Card className="run-summary">
              <div className="card-header">
                <div>
                  <h3>Run summary</h3>
                  <p>Review configuration before execution</p>
                </div>
                <span className="summary-icon">
                  <Workflow size={18} />
                </span>
              </div>
              <div className="summary-pair">
                <span>Run name</span>
                <b>{jobName || "Untitled run"}</b>
              </div>
              <div className="summary-pair">
                <span>Dataset</span>
                <b>
                  {backendDatasets.find(
                    (item) => item.id === selectedBackendDatasetId,
                  )?.name || "No backend dataset"}
                </b>
              </div>
              <div className="summary-pair">
                <span>Processing engine</span>
                <b>
                  {models.find((item) => item.id === jobEngine)?.name || "—"}
                </b>
              </div>
              <div className="summary-pair">
                <span>Output destination</span>
                <b>{outputTable}</b>
              </div>
              <div className="summary-divider" />
              <div className="run-warning">
                <Sparkles size={16} />
                <span>
                  Ready to process. Results will be saved to predictions parquet
                  and review queue.
                </span>
              </div>
              <Button
                variant="primary"
                className="run-button"
                icon={jobRunning ? RefreshCw : Play}
                disabled={jobRunning || !selectedBackendDatasetId}
                onClick={runPipeline}
              >
                {jobRunning ? "Running Splink engine…" : "Run pipeline"}
              </Button>
              <Button
                className="run-button"
                icon={Save}
                onClick={() =>
                  flash("Draft saved only in local browser state.")
                }
              >
                Save as draft
              </Button>
              <small className="demo-note">
                {selectedBackendDatasetId
                  ? "Backend dataset ready to execute"
                  : "Upload or ingest a dataset before running"}
              </small>
            </Card>
            <Card className="progress-card">
              <div className="card-header">
                <div>
                  <h3>Execution progress</h3>
                  <p>
                    {jobRunning
                      ? "Job running on backend"
                      : lastJob
                        ? "Last run completed"
                        : "No processing job created"}
                  </p>
                </div>
                <Gauge size={18} className="muted-icon" />
              </div>
              <div
                className="progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={jobRunning ? 100 : lastJob ? 100 : 0}
                aria-label="Job execution progress"
              >
                <span
                  style={{
                    width: jobRunning ? "100%" : lastJob ? "100%" : "0%",
                    transition: "width .4s ease",
                  }}
                  className={jobRunning ? "is-running" : ""}
                />
              </div>
              <div className="progress-meta">
                <b>
                  {jobRunning
                    ? `${jobElapsed}s`
                    : lastJob
                      ? `${lastJob.duration || "done"}`
                      : "—"}
                </b>
                <span>
                  {jobRunning
                    ? "Elapsed"
                    : lastJob
                      ? `${lastJob.pairs_scored || 0} pairs scored`
                      : "Idle"}
                </span>
              </div>
              <div className="terminal-box">
                <div>
                  <i />
                  <i />
                  <i />
                  <span>RUN LOG</span>
                </div>
                <code>
                  {jobRunning
                    ? `[fastapi] Processing ${selectedColumns.length > 0 ? selectedColumns.length + " selected column(s)" : "all columns"}… ${jobElapsed}s elapsed`
                    : lastJob
                      ? `[${lastJob.id}] Completed in ${lastJob.duration} · ${lastJob.pairs_scored || 0} pairs · ${lastJob.records_count || 0} records`
                      : "No job has been created yet."}
                </code>
              </div>
            </Card>
          </aside>
        </div>
      </>
    );
  }

  const renderReview = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={
          <>
            <Button icon={Download} onClick={exportReviews}>Export loaded pairs</Button>
            <label className="bulk-review-decision">
              <span>Bulk decision</span>
              <select value={bulkReviewDecision} onChange={event => setBulkReviewDecision(event.target.value)}>
                <option value="MATCH">MATCH</option>
                <option value="NON_MATCH">NON_MATCH</option>
                <option value="REVIEW">REVIEW</option>
              </select>
            </label>
            <Button
              variant="primary"
              icon={CheckCheck}
              disabled={!selectedReviewIds.size || bulkReviewSaving || reviewDecisionSaving || liveState !== 'live'}
              onClick={submitBulkReview}
            >
              Apply to selected ({selectedReviewIds.size})
            </Button>
          </>
        }
      />
      <div className="review-kpis">
        <div><span className="kpi-dot amber"/><div><b>{liveStats ? liveStats.review.toLocaleString() : '—'}</b><small>Awaiting review</small></div></div>
        <div><span className="kpi-dot mint"/><div><b>{reviewSummary ? reviewSummary.reviewed_today.toLocaleString() : '—'}</b><small>Reviewed today (audit)</small></div></div>
        <div><span className="kpi-dot blue"/><div><b>{reviewSummary?.agreement_rate !== null && reviewSummary?.agreement_rate !== undefined ? `${(reviewSummary.agreement_rate * 100).toFixed(1)}%` : '—'}</b><small>{reviewSummary?'Agreement rate (audit)':'Agreement rate unavailable'}</small></div></div>
      </div>
      <div className="review-progress">
        <div><span>Queue share</span><b>{liveStats ? `${Math.round(liveStats.review / Math.max(liveStats.total_pairs,1) * 100)}%` : '—'}</b></div>
        <div className="progress-track"><span style={{width:liveStats ? `${Math.round(liveStats.review / Math.max(liveStats.total_pairs,1) * 100)}%` : '0%'}}/></div>
      </div>
      <div className="review-workspace">
        <Card className="review-list-card">
          <div className="review-tabs">
            <button className={reviewTab==='queue'?'selected':''} onClick={()=>setReviewTab('queue')}>Pair queue <span>{reviewQueueTotal}</span></button>
            <button className={reviewTab==='history'?'selected':''} onClick={()=>setReviewTab('history')}>Reviewed history <span>{reviewHistoryTotal}</span></button>
          </div>
          <div className="table-toolbar review-toolbar">
            <div className="search-field"><Search size={15}/><input value={reviewSearch} onChange={event=>setReviewSearch(event.target.value)} placeholder={reviewTab==='history'?'Search audit history...':'Search loaded record pairs...'}/></div>
            {reviewTab==='queue'
              ? <div className="select-wrap"><Filter size={14}/><select aria-label="Filter pairs by decision" value={reviewDecisionFilter} onChange={event=>setReviewDecisionFilter(event.target.value)}><option value="REVIEW">REVIEW</option><option value="MATCH">MATCH</option><option value="NON_MATCH">NON_MATCH</option></select></div>
              : <span className="status-pill good"><i/>Audit live</span>}
          </div>
          {reviewTab === 'history' ? (
            <div className="pair-list">
              {reviewHistoryError && <div className="empty-state small-empty"><b>Could not load review history</b><span>{reviewHistoryError}</span><Button onClick={() => loadReviewHistory(1, false)}>Retry</Button></div>}
              {!reviewHistoryError && reviewHistory.filter(item => `${item.record_id_l} ${item.record_id_r} ${item.reviewer} ${item.reason}`.toLowerCase().includes(reviewSearch.toLowerCase())).map(item => (
                <div className="pair-item" key={item.request_id}>
                  <div className="pair-item-top"><b>{item.record_id_l}__{item.record_id_r}</b><StatusPill value={item.decision}/></div>
                  <p>{item.reason || 'No reason provided'}</p>
                  <div className="pair-item-bottom"><small>{item.reviewer || 'Unknown reviewer'}</small><small>{item.created_at ? new Date(item.created_at).toLocaleString() : 'Timestamp unavailable'}</small></div>
                </div>
              ))}
              {!reviewHistoryError && !reviewHistoryLoading && reviewHistory.length === 0 && <div className="empty-state small-empty"><SearchX size={22}/><b>No audit decisions yet</b><span>Saved review decisions will appear here.</span></div>}
              {reviewHistoryLoading && <div className="empty-state small-empty"><span>Loading review history…</span></div>}
            </div>
          ) : (
            <div className="pair-list">
              {reviewQueueError && <div className="empty-state small-empty"><b>Could not load review queue</b><span>{reviewQueueError}</span><Button onClick={() => loadReviewQueue(1, false)}>Retry</Button></div>}
              {!reviewQueueError && visibleReviews.map(row => (
                <div className="pair-list-row" key={row.id}>
                  <input
                    type="checkbox"
                    aria-label={`Select pair ${row.id}`}
                    checked={selectedReviewIds.has(row.id)}
                    disabled={bulkReviewSaving || reviewDecisionSaving || (!selectedReviewIds.has(row.id) && selectedReviewIds.size >= 100)}
                    onChange={event => setSelectedReviewIds(current => {
                      const next = new Set(current)
                      if (event.target.checked) next.add(row.id)
                      else next.delete(row.id)
                      return next
                    })}
                  />
                  <button
                    type="button"
                    className={cx('pair-item', selectedReview?.id===row.id&&'active')}
                    disabled={reviewDecisionSaving || bulkReviewSaving}
                    onClick={() => setSelectedReview(row)}
                  >
                    <div className="pair-item-top"><b>{row.id}</b><span className="score-chip">{Math.round(row.score*100)}% probability</span></div>
                    <div className="pair-names"><span>{row.left}</span><ArrowRight size={13}/><span>{row.right}</span></div>
                    <p>{row.reason}</p>
                    <div className="pair-item-bottom"><StatusPill value={row.decision}/><small>Model decision</small></div>
                  </button>
                </div>
              ))}
              {!reviewQueueError && !reviewQueueLoading && visibleReviews.length === 0 && (
                <div className="empty-state small-empty"><SearchX size={22}/><b>{liveState==='loading' || reviewQueueLoading ? 'Loading live pairs…' : liveState==='offline' ? 'Backend unavailable' : 'No pairs in this view'}</b><span>{reviewQueueError || (liveState==='live' ? 'Try another decision filter or refresh the queue.' : 'Live review data is not available.')}</span></div>
              )}
              {reviewQueueLoading && reviews.length > 0 && <div className="empty-state small-empty"><span>Loading more pairs…</span></div>}
            </div>
          )}
          <div className="review-list-footer">
            <span>{reviewTab==='history' ? `${reviewHistory.length} of ${reviewHistoryTotal} audit decisions` : `${reviews.length} of ${reviewQueueTotal} loaded pairs`}</span>
            <button
              disabled={reviewTab==='history'
                ? reviewHistoryLoading || reviewHistory.length >= reviewHistoryTotal
                : reviewQueueLoading || reviews.length >= reviewQueueTotal}
              onClick={() => reviewTab==='history'
                ? loadReviewHistory(reviewHistoryPage + 1, true)
                : loadReviewQueue(reviewQueuePage + 1, true)}
            >
              {reviewTab==='history' ? (reviewHistoryLoading ? 'Loading…' : 'Load more history') : (reviewQueueLoading ? 'Loading…' : 'Load more pairs')} <ChevronDown size={14}/>
            </button>
          </div>
        </Card>
        <Card className="review-detail-card">
          <div className="review-detail-head"><div><span className="section-kicker">PAIR INSPECTION</span><h3>{selectedReview?.id || 'Select a pair'}</h3><p>Compare source attributes and decision evidence.</p></div><StatusPill value={selectedReview?.decision || 'No selection'}/></div>
          {pairDetailLoading && <div className="empty-state small-empty"><span>Loading pair detail…</span></div>}
          {pairDetailError && <div className="empty-state small-empty"><b>Could not load pair detail</b><span>{pairDetailError}</span><Button onClick={() => setPairDetailRetry(value => value + 1)}>Retry</Button></div>}
          {!selectedReview && !pairDetailLoading && !pairDetailError && <div className="empty-state small-empty"><span>Select a pair to inspect its records.</span></div>}
          {selectedReview && !pairDetailLoading && !pairDetailError && pairDetail && (
            <>
              <div className="record-compare">
                {['record_a', 'divider', 'record_b'].map(key => {
                  if (key === 'divider') return <div className="compare-divider" key={key}><span>VS</span></div>
                  const record = pairDetail[key] || {}
                  return <div className="record-card" key={key}>
                    <span className="record-label">RECORD {key === 'record_a' ? 'A' : 'B'}</span><h4>{record.record_id || '—'}</h4>
                    <div><small>Full name</small><b>{[record.first_name, record.last_name].filter(Boolean).join(' ') || '—'}</b></div>
                    <div><small>Email</small><b>{record.email || '—'}</b></div>
                    <div><small>Phone</small><b>{record.phone_number || '—'}</b></div>
                    <div><small>Date of birth</small><b>{record.dob || '—'}</b></div>
                    <div><small>Full address</small><b>{[record.address, record.city, record.state, record.country].filter(Boolean).join(', ') || '—'}</b></div>
                  </div>
                })}
              </div>
              <div className="match-evidence">
                <div className="evidence-head"><div><b>Model evidence</b><small>Live pair evidence from Splink</small></div><strong>{Math.round(selectedReview.score*100)}<small>%</small></strong></div>
                <div className="evidence-track"><span style={{width:`${selectedReview.score*100}%`}}/></div>
                <p>{selectedReview.reason}</p>
              </div>
              <div className="decision-panel">
                <b>Human decision</b><p>Choose whether these records represent the same entity. Decisions are recorded separately from model predictions.</p>
                <div className="reviewer-fields">
                  <Field label="Reviewer name"><input value={reviewerName} onChange={event => setReviewerName(event.target.value)} autoComplete="name" /></Field>
                  <Field label="Decision reason"><input value={reviewReason} onChange={event => setReviewReason(event.target.value)} /></Field>
                </div>
                <div className="decision-buttons">
                  <Button variant="success" icon={CheckCheck} disabled={reviewDecisionSaving || liveState !== 'live'} onClick={() => decideReview('MATCH')}>{reviewDecisionSaving ? 'Saving…' : 'Confirm match'}</Button>
                  <Button variant="danger" icon={X} disabled={reviewDecisionSaving || liveState !== 'live'} onClick={() => decideReview('NON_MATCH')}>Not a match</Button>
                  <Button icon={Clock3} disabled={reviewDecisionSaving || liveState !== 'live'} onClick={() => decideReview('REVIEW')}>Keep in review</Button>
                </div>
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  )

  const renderEntities = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={
          <Button icon={RefreshCw} disabled={entitiesLoading} onClick={loadEntities}>
            {entitiesLoading ? 'Refreshing…' : 'Refresh'}
          </Button>
        }
      />
      <div className="review-kpis">
        <div><span className="kpi-dot blue"/><div><b>{entities.length.toLocaleString()}</b><small>Resolved entities</small></div></div>
        <div><span className="kpi-dot mint"/><div><b>{entities.reduce((acc, cur) => acc + (Number(cur.member_count) || 0), 0)}</b><small>Total clustered records</small></div></div>
        <div><span className="kpi-dot amber"/><div><b>{conflicts.length.toLocaleString()}</b><small>Documented conflicts</small></div></div>
      </div>
      <div className="review-workspace">
        <Card className="review-list-card">
          <div className="review-tabs">
            <button className={entityTab === 'clusters' ? 'selected' : ''} onClick={() => setEntityTab('clusters')}>
              Resolved entities <span>{entities.length}</span>
            </button>
            <button className={entityTab === 'conflicts' ? 'selected' : ''} onClick={() => setEntityTab('conflicts')}>
              Conflicts <span>{conflicts.length}</span>
            </button>
          </div>
          {entityTab === 'clusters' ? (
            <div className="pair-list">
              {entities.map(ent => (
                <button
                  type="button"
                  key={ent.entity_id}
                  className={cx('pair-item', selectedEntity?.entity_id === ent.entity_id && 'active')}
                  onClick={() => selectEntity(ent)}
                >
                  <div className="pair-item-top">
                    <b>{ent.entity_id}</b>
                    <StatusPill value={ent.entity_status || 'ACTIVE'} />
                  </div>
                  <div className="pair-names">
                    <span>{[ent.first_name, ent.last_name].filter(Boolean).join(' ') || ent.master_record_id}</span>
                  </div>
                  <p>{ent.city ? `${ent.city} · ` : ''}{ent.email || ent.phone_number || 'Master identity profile'}</p>
                  <div className="pair-item-bottom">
                    <small>{ent.member_count} member records</small>
                    <small>{ent.updated_at ? new Date(ent.updated_at).toLocaleDateString() : '—'}</small>
                  </div>
                </button>
              ))}
              {entities.length === 0 && (
                <div className="empty-state small-empty">
                  <SearchX size={22}/>
                  <b>No entities found</b>
                  <span>Supabase entity_map has no recorded entities.</span>
                </div>
              )}
            </div>
          ) : (
            <div className="pair-list">
              {conflicts.map(conf => (
                <div className="pair-item" key={conf.conflict_id}>
                  <div className="pair-item-top">
                    <b>{conf.conflict_type}</b>
                    <StatusPill value={conf.status} />
                  </div>
                  <div className="pair-names">
                    <span>{conf.record_id_l}</span>
                    <ArrowRight size={13} />
                    <span>{conf.record_id_r}</span>
                  </div>
                  <p>{conf.description}</p>
                  <div className="pair-item-bottom">
                    <small>Entity: {conf.entity_id || 'Unassigned'}</small>
                    <small>{conf.created_at ? new Date(conf.created_at).toLocaleDateString() : '—'}</small>
                  </div>
                </div>
              ))}
              {conflicts.length === 0 && (
                <div className="empty-state small-empty">
                  <CheckCircle2 size={22}/>
                  <b>No conflicts recorded</b>
                  <span>All customer identities reconciled without conflicts.</span>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card className="review-detail-card">
          <div className="review-detail-head">
            <div>
              <span className="section-kicker">ENTITY REPRESENTATION</span>
              <h3>{selectedEntity?.entity_id || 'Select an entity'}</h3>
              <p>Master golden customer profile and source records membership.</p>
            </div>
            {selectedEntity && <StatusPill value={selectedEntity.entity_status || 'ACTIVE'} />}
          </div>

          {selectedEntity && (
            <>
              <div className="record-card" style={{ marginBottom: '14px' }}>
                <span className="record-label">MASTER GOLDEN CUSTOMER</span>
                <h4>{selectedEntity.master_record_id || selectedEntity.entity_id}</h4>
                <div><small>Full name</small><b>{[selectedEntity.first_name, selectedEntity.last_name].filter(Boolean).join(' ') || '—'}</b></div>
                <div><small>Email</small><b>{selectedEntity.email || '—'}</b></div>
                <div><small>Phone</small><b>{selectedEntity.phone_number || '—'}</b></div>
                <div><small>City</small><b>{selectedEntity.city || '—'}</b></div>
              </div>

              <div className="card-header" style={{ padding: '0 0 8px 0' }}>
                <div>
                  <h4 style={{ margin: 0, fontSize: '13px' }}>Cluster Memberships ({entityMembers.length})</h4>
                  <p style={{ margin: 0, fontSize: '11px', color: '#64748b' }}>Records linked to this master entity identity</p>
                </div>
              </div>

              {entityMembersLoading && (
                <div className="empty-state small-empty"><span>Loading member records…</span></div>
              )}

              {!entityMembersLoading && (
                <div className="table-scroll-mini" style={{ maxHeight: '280px' }}>
                  <table className="mini-data-table">
                    <thead>
                      <tr>
                        <th>Record ID</th>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Phone</th>
                        <th>Address</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entityMembers.map(mem => (
                        <tr key={mem.record_id}>
                          <td><b>{mem.record_id}</b></td>
                          <td>{[mem.first_name, mem.last_name].filter(Boolean).join(' ') || '—'}</td>
                          <td>{mem.email || '—'}</td>
                          <td>{mem.phone_number || '—'}</td>
                          <td>{[mem.address, mem.city].filter(Boolean).join(', ') || '—'}</td>
                          <td><span className="status-pill neutral">{mem.membership_source || 'linkage'}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {!selectedEntity && (
            <div className="empty-state small-empty">
              <span>Choose an entity cluster from the left panel to inspect its master customer record and source memberships.</span>
            </div>
          )}
        </Card>
      </div>
    </>
  )

  const renderHistory = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={<Button icon={Download} onClick={exportRunHistory}>Export loaded runs</Button>}
      />
      <div className="metrics-grid compact-metrics">
        <MetricCard
          label="Total runs"
          value={runRegistryTotal.toLocaleString()}
          change={runRegistryError ? 'Unavailable' : 'Backend registry'}
          caption="registered runs"
          icon={Workflow}
          tone="blue"
        />
        <MetricCard
          label="Successful"
          value={String(runs.filter(run => ['completed', 'success', 'succeeded'].includes(String(run.status).toLowerCase())).length)}
          change="Loaded page"
          caption="completed in loaded runs"
          icon={CheckCircle2}
          tone="mint"
        />
        <MetricCard
          label="Needs attention"
          value={String(runs.filter(run => ['failed', 'error', 'cancelled'].includes(String(run.status).toLowerCase())).length)}
          change="Loaded page"
          caption="failed or cancelled in loaded runs"
          icon={AlertTriangle}
          tone="amber"
        />
      </div>
      <Card className="table-card">
        <div className="table-toolbar">
          <div className="table-heading">
            <h3>Processing runs</h3>
            <p>Run records from the backend registry</p>
          </div>
          <div className="toolbar-right">
            <Button
              icon={RefreshCw}
              disabled={runRegistryLoading}
              onClick={() => loadRuns(1, false)}
            >
              Refresh
            </Button>
          </div>
        </div>
        <Table
          columns={[
            { key: "id", label: "Run ID" },
            { key: "dataset", label: "Dataset" },
            { key: "status", label: "Status" },
            { key: "started", label: "Started" },
          ]}
          rows={runs}
          empty={runRegistryError || (runRegistryLoading ? 'Loading run history…' : 'No run history available from backend')}
        />
        <div className="table-footer">
          <span>{runs.length} of {runRegistryTotal} runs</span>
          <button
            disabled={runRegistryLoading || runs.length >= runRegistryTotal}
            onClick={() => loadRuns(runRegistryPage + 1, true)}
          >
            {runRegistryLoading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      </Card>
      <Card className="output-card">
        <div className="card-header">
          <div>
            <h3>Output destinations</h3>
            <p>Configured export targets</p>
          </div>
        </div>
        {(() => {
          if (!outputDestinations || !outputDestinations.length) {
            return <div className="empty-state small-empty"><Database size={20}/><b>No output destinations</b><span>The backend does not expose registered output destinations.</span></div>
          }
          return (
            <div className="output-list">
              {outputDestinations.map(item => (
                <div key={item.id} className="output-row" style={{ alignItems: 'center', gap: '12px' }}>
                  <div className="output-icon" style={{ width: 24, height: 24, display: 'grid', placeItems: 'center', borderRadius: 5 }}>
                    {item.type === 'supabase' && <Database size={18} />}
                    {item.type === 's3' && <CloudUpload size={18} />}
                    {item.type === 'webhook' && <ExternalLink size={18} />}
                  </div>
                  <div style={{ flex: 1 }}>
                    <b>{item.name}</b>{item.builtin && <small style={{ color: '#8897a9' }}> (built-in)</small>}
                  </div>
                  <small style={{ color: '#8897a9' }}>{item.type}</small>
                </div>
              ))}
            </div>
          )
        })()}
      </Card>
    </>
  );

  const renderModels = () => {
    const activeVersion = modelInfo?.model_version || null
    const pageSize = 15
    const totalPages = Math.max(1, Math.ceil(modelVersions.length / pageSize))
    const page = Math.min(modelPage, totalPages)
    const pagedVersions = modelVersions.slice((page - 1) * pageSize, page * pageSize)
    return <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={<>
          <Button variant="secondary" icon={RefreshCw} onClick={loadModelData}>Refresh</Button>
          <Button variant="primary" icon={Play} disabled={retrainStatus === 'running'} onClick={async () => {
            if (retrainStatus === 'running') return
            setRetrainStatus('running')
            setRetrainLog('')
            retrainOffset.current = 0
            try {
              await dedupApi.startRetrain({ skip_blocking_benchmark: true })
              flash('Retrain started in background.')
            } catch (e) {
              flash(`Retrain failed: ${e.message || e}`)
              setRetrainStatus(null)
            }
          }}>{retrainStatus === 'running' ? 'Running...' : 'Retrain'}</Button>
        </>}
      />
      {activeVersion && <div className="info-banner"><BrainCircuit size={18}/><div><b>Active model</b><p>Version <code>{activeVersion}</code> · match threshold <b>{modelInfo.threshold_match}</b> · review threshold <b>{modelInfo.threshold_review}</b></p></div></div>}
      {!activeVersion && <div className="info-banner amber-banner"><CircleAlert size={17}/><div><b>No active model</b><p>Run a full pipeline first to create a model version before rolling back or retraining.</p></div></div>}
      {retrainStatus === 'running' && <Card className="retrain-log-card"><div className="card-header"><div><h3>Retrain log</h3><p>Live output from the background pipeline</p></div><Terminal size={18} className="muted-icon"/></div><pre className="retrain-log-pre">{retrainLog || 'Waiting for output…'}</pre></Card>}
      {modelVersions.length === 0
        ? <Card><div className="empty-state"><SearchX size={20}/><b>No model versions yet</b><span>Run the full pipeline to train your first model.</span></div></Card>
        : <>
          <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {pagedVersions.map((v, idx) => (
            <Card key={v.version} className={cx(v.version===activeVersion&&'model-card','version-row')}>
              <div style={{display:'flex',alignItems:'center',gap:12}}>
                <span style={{fontWeight:700,width:100}}>{v.version}</span>
                <StatusPill value={v.complete ? 'Complete' : 'Incomplete'} style={{width:90}} />
                <span style={{color:'var(--muted)',flex:1,fontSize:12}}>{new Date(v.created_at||0).toLocaleString('id-ID')}</span>
                <span style={{width:80,fontSize:12,textAlign:'right'}}>{v.scope === 'full' ? 'Full' : 'Sample'}</span>
                <span style={{width:100,fontSize:12,textAlign:'right'}}>{v.pairs_scored ? v.pairs_scored.toLocaleString() : '—'}</span>
                {v.version !== activeVersion && (
                  <button
                    className="text-link"
                    style={{marginLeft:20,fontSize:12}}
                    onClick={async () => {
                      try {
                        await dedupApi.rollbackModel(v.version)
                        flash(`Rolled back to ${v.version}.`)
                        loadModelData()
                      } catch (e) {
                        flash(`Rollback failed: ${e.message || e}`)
                      }
                    }}
                  >Roll back</button>
                )}
                {v.version === activeVersion && <span style={{marginLeft:20,fontSize:12,color:'var(--violet)'}}>● Current</span>}
              </div>
            </Card>
            ))}
          </div>
          {totalPages > 1 && <div className="table-footer">
            <span>Page {page} of {totalPages} · {modelVersions.length} versions</span>
            <div>
              <button disabled={page <= 1} onClick={() => setModelPage(page - 1)}><ChevronLeft size={14}/></button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => <button key={p} className={p === page ? 'current' : ''} onClick={() => setModelPage(p)}>{p}</button>)}
              <button disabled={page >= totalPages} onClick={() => setModelPage(page + 1)}><ChevronRight size={14}/></button>
            </div>
          </div>}
        </>
      }
    </>
  }

  const renderAnalytics = () => {
    const total = liveStats?.total_pairs || 0
    const counts = liveStats ? [
      ['MATCH', liveStats.matches, 'green'],
      ['REVIEW', liveStats.review, 'amber'],
      ['NON_MATCH', liveStats.non_matches, 'grey'],
    ] : []
    return <>
      <PageHeader title={meta[0]} subtitle={meta[1]} actions={<div className="date-control"><CalendarDays size={15}/> All available data</div>} />
      <div className="info-banner amber-banner"><CircleAlert size={17}/><div><b>Prediction counts are not evaluation metrics</b><p>Precision, recall, and F1 require independently reviewed gold labels and documented evaluation splits. Those inputs are not available through the current API.</p></div></div>
      <div className="metrics-grid"><MetricCard label="Precision" value="—" change="Unavailable" caption="gold evaluation required" icon={TargetIcon} tone="mint"/><MetricCard label="Recall" value="—" change="Unavailable" caption="gold evaluation required" icon={Gauge} tone="blue"/><MetricCard label="F1 score" value="—" change="Unavailable" caption="gold evaluation required" icon={Activity} tone="violet"/><MetricCard label="Review rate" value={total ? `${((liveStats.review / total) * 100).toFixed(1)}%` : '—'} change={liveState==='live'?'Live':'Unavailable'} caption="live output share" icon={ListChecks} tone="amber" trend="down"/></div>
      <div className="analytics-grid">
        <Card className="chart-card"><div className="card-header"><div><h3>Evaluation trend</h3><p>No evaluation history endpoint is available.</p></div><StatusPill value="Unavailable"/></div><div className="empty-state small-empty"><SearchX size={20}/><b>No evaluation runs</b><span>Record gold-label evaluations before displaying model performance.</span></div></Card>
        <Card className="quality-card">
          <div className="card-header"><div><h3>Prediction decisions</h3><p>Live Splink output counts, not quality scores</p></div></div>
          {total ? <div className="quality-rows">{counts.map(([label, count, color]) => <div key={label}><div><span>{label}</span><b>{count.toLocaleString()} · {((count / total) * 100).toFixed(1)}%</b></div><div className="quality-track"><i className={color} style={{width:`${(count / total) * 100}%`}}/></div></div>)}</div> : <div className="empty-state small-empty"><SearchX size={20}/><b>Prediction data unavailable</b><span>Connect to FastAPI to view current decision counts.</span></div>}
        </Card>
        <Card className="evaluation-breakdown"><div className="card-header"><div><h3>Evaluation checklist</h3><p>Evidence required before trusting model metrics</p></div></div><div className="checklist-item"><CheckCircle2 size={16}/><div><b>Gold labels separated from silver labels</b><small>Use human-reviewed labels as the trusted evaluation reference.</small></div><StatusPill value="Required"/></div><div className="checklist-item"><AlertTriangle size={16}/><div><b>Disputed identity cases documented</b><small>Record known conflicts and adjudication decisions.</small></div><StatusPill value="Review"/></div><div className="checklist-item"><CircleDot size={16}/><div><b>Threshold and model version captured</b><small>Store the exact configuration used for every evaluation.</small></div><StatusPill value="Planned"/></div></Card>
      </div>
    </>
  }

  const renderDatabase = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={<Button variant="primary" icon={Plus} onClick={() => setShowSourceModal(true)}>Add connection</Button>}
      />
      <div className="db-layout">
        <div className="db-main">
          <Card className="db-connection">
            <div className="connection-card large">
              <div className="connection-brand"><Database size={22} /></div>
              <div className="connection-info">
                <div>
                  <h3>Supabase PostgreSQL</h3>
                  <StatusPill value={databaseStatus?.status === "connected" ? "Connected" : "Unavailable"} />
                </div>
                <p>Schema public · read-only API inspection</p>
                <small>{databaseStatus?.status === "connected" ? `${databaseStatus.table_count} tables available` : "Database status unavailable"}</small>
              </div>
              <Button
                onClick={async () => {
                  try {
                    const status = await dedupApi.getDatabaseStatus()
                    const tables = await dedupApi.getDatabaseTables()
                    setDatabaseStatus(status)
                    setDatabaseTables(tables.tables || [])
                    setDatabaseIngestibleTables(tables.ingestible_tables || [])
                    setConnectionStatus(status.status === "connected" ? "Connected" : "Unavailable")
                    flash(status.status === "connected" ? "Database connection verified." : "Database connection unavailable.")
                  } catch (error) {
                    setConnectionStatus("Unavailable")
                    setDatabaseStatus({ status: 'unavailable', table_count: 0 })
                    setDatabaseTables([])
                    setDatabaseIngestibleTables([])
                    flash(`Database check failed: ${error.message || error}`)
                  }
                }}
                icon={RefreshCw}
              >
                Test connection
              </Button>
            </div>
            <div className="db-properties">
              <div><span>Engine</span><b>Supabase PostgreSQL</b></div>
              <div><span>Host</span><b>{databaseStatus?.status === "connected" ? "Configured" : "Unavailable"}</b></div>
              <div><span>Schema</span><b>public</b></div>
              <div><span>Access mode</span><b>Read-only</b></div>
            </div>
          </Card>
          <Card className="schema-card">
            <div className="card-header">
              <div><h3>Schema browser</h3><p>Tables returned by the read-only FastAPI database endpoint.</p></div>
              <Button
                icon={RefreshCw}
                onClick={async () => {
                  try {
                    const tables = await dedupApi.getDatabaseTables()
                    setDatabaseTables(tables.tables || [])
                    setDatabaseIngestibleTables(tables.ingestible_tables || [])
                    flash(`Loaded ${tables.total} tables.`)
                  } catch (error) {
                    setDatabaseTables([])
                    setDatabaseIngestibleTables([])
                    flash(`Schema refresh failed: ${error.message || error}`)
                  }
                }}
              >
                Refresh
              </Button>
            </div>
            <div className="schema-tree">
              <div className="schema-root"><Database size={16} /><b>public</b><span>Supabase schema</span></div>
              {databaseTables.map(table => (
                <div className="schema-group" key={table}>
                  <div><Table2 size={14} /><b>{table}</b><small>Table</small></div>
                  <div className="schema-group-action">
                    <span>Read-only</span>
                    <button
                      type="button"
                      className="schema-preview-button"
                      aria-expanded={databaseColumnPreview?.table === table}
                      onClick={() => toggleDatabaseColumnPreview(table)}
                    >
                      {databaseColumnPreview?.table === table ? 'Hide columns' : 'Preview columns'}
                    </button>
                    {databaseIngestibleTables.includes(table) && (
                      <button
                        type="button"
                        className="schema-ingest-button"
                        disabled={Boolean(databaseIngestingTable)}
                        aria-label={`Import ${table} as a dataset`}
                        onClick={() => importDatabaseTable(table)}
                      >
                        <CloudUpload size={13} />
                        {databaseIngestingTable === table ? 'Importing…' : 'Import dataset'}
                      </button>
                    )}
                  </div>
                  {databaseColumnPreview?.table === table && (
                    <div className="schema-column-preview" role="status">
                      {databaseColumnPreview.loading ? 'Loading columns…' : databaseColumnPreview.error
                        ? databaseColumnPreview.error
                        : databaseColumnPreview.columns.length
                          ? databaseColumnPreview.columns.map(column => (
                            <span key={column.name}>{column.name} <small>{column.type}</small></span>
                          ))
                          : 'No columns found.'}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
          <Card className="schema-card">
            <div className="card-header">
              <div>
                <h3>Supabase</h3>
                <p>Tabel Supabase PostgreSQL — schema: public.</p>
              </div>
              <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
                <StatusPill value={supabaseStatus?.status === 'connected' ? 'Connected' : supabaseStatus ? 'Unavailable' : 'Loading…'} />
                <Button
                  icon={RefreshCw}
                  disabled={supabaseRefreshing}
                  onClick={async () => {
                    setSupabaseRefreshing(true)
                    try {
                      const [sStatus, sTables, sDatasets] = await Promise.all([
                        dedupApi.getSupabaseStatus(),
                        dedupApi.getSupabaseTables(),
                        dedupApi.getSupabaseDatasets(),
                      ])
                      setSupabaseStatus(sStatus)
                      setSupabaseTables(sTables?.tables || [])
                      setSupabaseDatasets(sDatasets?.datasets || [])
                      flash(`Supabase: ${sTables?.total ?? 0} tables loaded.`)
                    } catch (error) {
                      setSupabaseStatus({ status: 'unavailable' })
                      flash(`Supabase refresh failed: ${error.message || error}`)
                    } finally {
                      setSupabaseRefreshing(false)
                    }
                  }}
                >
                  {supabaseRefreshing ? 'Refreshing…' : 'Refresh'}
                </Button>
              </div>
            </div>
            <div className="schema-tree">
              <div className="schema-root"><Database size={16} /><b>public</b><span>Supabase schema</span></div>
              {supabaseTables.map(table => {
                const datasetInfo = supabaseDatasets.find(d => d.name === table)
                return (
                  <div className="schema-group" key={table}>
                    <div>
                      <Table2 size={14} />
                      <b>{table}</b>
                      <small>{datasetInfo ? `${datasetInfo.rows.toLocaleString()} rows` : 'Table'}</small>
                    </div>
                    <div className="schema-group-action">
                      <span>Read-only</span>
                      <button
                        type="button"
                        className="schema-preview-button"
                        aria-expanded={supabaseColumnPreview?.table === table}
                        onClick={() => toggleSupabaseColumnPreview(table)}
                      >
                        {supabaseColumnPreview?.table === table ? 'Hide columns' : 'Preview columns'}
                      </button>
                      <button
                        type="button"
                        className="schema-preview-button"
                        style={{ marginLeft: '6px', color: '#4f83dc' }}
                        aria-expanded={supabaseDataPreview?.table === table}
                        onClick={() => toggleSupabaseDataPreview(table)}
                      >
                        <Eye size={12} style={{ marginRight: '3px' }} />
                        {supabaseDataPreview?.table === table ? 'Hide data' : 'Preview data'}
                      </button>
                      {['customers', 'processed_customers'].includes(table) && (
                        <button
                          type="button"
                          className="schema-ingest-button"
                          disabled={Boolean(supabaseIngestingTable)}
                          aria-label={`Import ${table} from Supabase as a dataset`}
                          onClick={() => importSupabaseTable(table)}
                        >
                          <CloudUpload size={13} />
                          {supabaseIngestingTable === table ? 'Importing…' : 'Import dataset'}
                        </button>
                      )}
                    </div>

                    {supabaseColumnPreview?.table === table && (
                      <div className="schema-column-preview" role="status">
                        {supabaseColumnPreview.loading ? 'Loading columns from Supabase…' : supabaseColumnPreview.error
                          ? supabaseColumnPreview.error
                          : supabaseColumnPreview.columns.length
                            ? supabaseColumnPreview.columns.map(column => (
                              <span key={column.name}>
                                {column.name} <small>{column.type}</small>
                                {column.nullable ? <small style={{ opacity: 0.6 }}>(opt)</small> : null}
                              </span>
                            ))
                            : 'No columns found.'}
                      </div>
                    )}

                    {supabaseDataPreview?.table === table && (
                      <div className="schema-data-preview" role="region" aria-label={`Preview data ${table}`}>
                        <div className="data-preview-header">
                          <b>Preview data (read-only, max 15 baris)</b>
                          {supabaseDataPreview.loading && <span>Loading data…</span>}
                        </div>
                        {supabaseDataPreview.error && (
                          <div className="preview-error">{supabaseDataPreview.error}</div>
                        )}
                        {!supabaseDataPreview.loading && !supabaseDataPreview.error && (
                          supabaseDataPreview.rows?.length > 0 ? (
                            <div className="table-scroll-mini">
                              <table className="mini-data-table">
                                <thead>
                                  <tr>
                                    {supabaseDataPreview.columns.map(col => (
                                      <th key={col}>{col}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {supabaseDataPreview.rows.map((row, rIdx) => (
                                    <tr key={rIdx}>
                                      {supabaseDataPreview.columns.map(col => (
                                        <td key={col}>{row[col] !== null && row[col] !== undefined ? String(row[col]) : <em style={{ opacity: 0.4 }}>null</em>}</td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <div className="preview-empty">Tabel kosong (0 rows).</div>
                          )
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
              {supabaseTables.length === 0 && (
                <div className="empty-state small-empty">
                  <SearchX size={18}/>
                  <b>{supabaseStatus?.status === 'connected' ? 'No tables found' : 'Supabase not connected'}</b>
                  <span>{supabaseStatus?.status === 'connected' ? 'No tables in schema public.' : 'Click Refresh to load Supabase tables.'}</span>
                </div>
              )}
            </div>
          </Card>
        </div>
        <div className="db-side">
          <Card className="security-card">
            <span className="security-symbol"><ShieldCheck size={19} /></span>
            <h3>Connection security</h3>
            <p>Production credentials remain server-side. Source tables are read-only; eligible tables can be copied into the workspace as datasets.</p>
          </Card>
        </div>
      </div>
    </>
  )

  const renderSettings = () => (
    <>
      <PageHeader
        title={meta[0]}
        subtitle={meta[1]}
        actions={<Button variant="primary" icon={Save} disabled={settingsLoading || settingsSaving} onClick={saveWorkspaceSettings}>{settingsSaving ? 'Saving…' : 'Save changes'}</Button>}
      />
      {settingsError && <div className="info-banner amber-banner"><CircleAlert size={17}/><div><b>Settings need attention</b><p>{settingsError}</p><Button onClick={loadWorkspaceSettings}>Retry loading settings</Button></div></div>}
      <div className="settings-layout">
        <Card className="settings-menu">
          <button className="selected" type="button"><Settings size={15}/> General <ChevronRight size={14}/></button>
          <button type="button" onClick={() => document.getElementById('settings-appearance')?.scrollIntoView({ behavior: 'smooth' })}><Sun size={15}/> Appearance <ChevronRight size={14}/></button>
          <button type="button" onClick={() => document.getElementById('settings-processing')?.scrollIntoView({ behavior: 'smooth' })}><Workflow size={15}/> Processing defaults <ChevronRight size={14}/></button>
          <button type="button" onClick={() => document.getElementById('settings-output')?.scrollIntoView({ behavior: 'smooth' })}><Database size={15}/> Output defaults <ChevronRight size={14}/></button>
          <button type="button" onClick={() => flash('Export preferences are not available in the current settings API.')}><Download size={15}/> Export preferences <ChevronRight size={14}/></button>
          <button type="button" onClick={() => flash('Security preferences are managed by the deployment administrator.')}><ShieldCheck size={15}/> Security <ChevronRight size={14}/></button>
        </Card>
        <div className="settings-content">
          <Card className="settings-card">
            <div className="settings-card-title"><div><h3>Workspace profile</h3><p>Identity and regional preferences for this environment.</p></div><Layers3 size={18}/></div>
            <div className="form-grid">
              <Field label="Workspace name"><input value={workspaceSettings.workspace_name} disabled={settingsLoading} onChange={event => setWorkspaceSetting('workspace_name', event.target.value)}/></Field>
              <Field label="Timezone"><select value={workspaceSettings.timezone} disabled={settingsLoading} onChange={event => setWorkspaceSetting('timezone', event.target.value)}><option>Asia/Jakarta</option><option>UTC</option><option>Asia/Singapore</option></select></Field>
              <Field label="Default landing page"><select value={workspaceSettings.default_landing_page} disabled={settingsLoading} onChange={event => setWorkspaceSetting('default_landing_page', event.target.value)}><option value="dashboard">Overview</option><option value="processing">Processing</option><option value="review">Review queue</option></select></Field>
              <Field label="Date format"><select value={workspaceSettings.date_format} disabled={settingsLoading} onChange={event => setWorkspaceSetting('date_format', event.target.value)}><option>DD MMM YYYY</option><option>YYYY-MM-DD</option><option>MM/DD/YYYY</option></select></Field>
            </div>
          </Card>
          <Card className="settings-card" id="settings-appearance">
            <div className="settings-card-title"><div><h3>Appearance</h3><p>Choose a workspace display theme.</p></div><Moon size={18}/></div>
            <div className="theme-choices">
              <button className={workspaceSettings.theme === 'light' ? 'chosen' : ''} onClick={() => { setWorkspaceSetting('theme', 'light'); setDark(false) }}><div className="theme-thumb light-thumb"><i/><i/><i/></div><b>Light</b><small>Bright and clean</small></button>
              <button className={workspaceSettings.theme === 'dark' ? 'chosen' : ''} onClick={() => { setWorkspaceSetting('theme', 'dark'); setDark(true) }}><div className="theme-thumb dark-thumb"><i/><i/><i/></div><b>Dark</b><small>Low-light workspace</small></button>
            </div>
          </Card>
          <Card className="settings-card" id="settings-processing">
            <div className="settings-card-title"><div><h3>Processing defaults</h3><p>Safe defaults applied when creating a new run.</p></div><SlidersHorizontal size={18}/></div>
            <div className="setting-toggle"><div><b>Preserve source data</b><small>Never overwrite the original source dataset.</small></div><button aria-label="Preserve source data" aria-pressed={workspaceSettings.preserve_source_data} className={cx('toggle-switch', workspaceSettings.preserve_source_data && 'on')} onClick={() => setWorkspaceSetting('preserve_source_data', !workspaceSettings.preserve_source_data)}><i/></button></div>
            <div className="setting-toggle"><div><b>Require output confirmation</b><small>Ask for confirmation before writing to a destination table.</small></div><button aria-label="Require output confirmation" aria-pressed={workspaceSettings.require_output_confirmation} className={cx('toggle-switch', workspaceSettings.require_output_confirmation && 'on')} onClick={() => setWorkspaceSetting('require_output_confirmation', !workspaceSettings.require_output_confirmation)}><i/></button></div>
            <div className="setting-toggle"><div><b>Keep processing audit trail</b><small>Store run configuration, status, and output references.</small></div><button aria-label="Keep processing audit trail" aria-pressed={workspaceSettings.keep_processing_audit_trail} className={cx('toggle-switch', workspaceSettings.keep_processing_audit_trail && 'on')} onClick={() => setWorkspaceSetting('keep_processing_audit_trail', !workspaceSettings.keep_processing_audit_trail)}><i/></button></div>
          </Card>
          <Card className="settings-card" id="settings-output">
            <div className="settings-card-title"><div><h3>Output defaults</h3><p>Where processed results are saved by default.</p></div><Database size={18}/></div>
            <Field label="Default output destination" hint="Target used when saving processed results.">
              <select value={workspaceSettings.default_output_destination} disabled={settingsLoading} onChange={event => setWorkspaceSetting('default_output_destination', event.target.value)}>
                {outputDestinations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
            <p className="settings-footnote-inline">Destination management lives in Run history → Output destinations.</p>
          </Card>
          <div className="settings-footnote"><ShieldCheck size={15}/> Workspace preferences persist on the backend. Connection credentials and output profiles are not included.</div>
        </div>
      </div>
    </>
  )

  const renderPage = () => {
    switch (activePage) {
      case 'dashboard': return renderDashboard()
      case 'sources': return renderSources()
      case 'datasets': return renderDatasets()
      case 'processing': return renderProcessing()
      case 'review': return renderReview()
      case 'entities': return renderEntities()
      case 'history': return renderHistory()
      case 'models': return renderModels()
      case 'analytics': return renderAnalytics()
      case 'database': return renderDatabase()
      case 'settings': return renderSettings()
      default: return renderDashboard()
    }
  }

  return (
    <div className={cx("app-shell", dark && "dark-theme")}>
      <aside
        className={cx(
          "sidebar",
          collapsed && "collapsed",
          mobileMenu && "mobile-open",
        )}
      >
        <div className="brand-row">
          <span className="brand-mark">
            <Layers3 size={19} />
          </span>
          <div className="brand-copy">
            <b>Hyperdata</b>
            <small>INTELLIGENCE</small>
          </div>
          <button
            className="collapse-button"
            onClick={() => setCollapsed((value) => !value)}
            title="Collapse sidebar"
          >
            {collapsed ? (
              <PanelLeftOpen size={16} />
            ) : (
              <PanelLeftClose size={16} />
            )}
          </button>
          <button className="mobile-close" onClick={() => setMobileMenu(false)}>
            <X size={18} />
          </button>
        </div>
        <button
          className="workspace-switch"
          onClick={() => flash("Workspace switcher is a visual placeholder.")}
        >
          <span className="workspace-avatar">ND</span>
          <span className="workspace-copy">
            <b>Data workspace</b>
            <small>Personal environment</small>
          </span>
          <ChevronDown size={14} />
        </button>
        <nav className="main-nav">
          {navigation.map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-group-label">{group.group}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    title={collapsed ? item.label : ""}
                    className={cx(
                      "nav-link",
                      activePage === item.id && "active",
                    )}
                    onClick={() => navigate(item.id)}
                  >
                    <Icon size={17} strokeWidth={1.8} />
                    <span>{item.label}</span>
                    {(item.id === 'review' ? reviewQueueTotal > 0 : item.count) && <em>{item.id === 'review' ? reviewQueueTotal.toLocaleString() : item.count}</em>}
                    {activePage === item.id && <i className="active-mark" />}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="help-card">
            <span>
              <Sparkles size={15} />
            </span>
            <div>
              <b>Build something smart</b>
              <small>Explore platform capabilities</small>
            </div>
            <ArrowUpRight size={14} />
          </div>
          <div className="sidebar-user">
            <span className="user-avatar">DA</span>
            <div className="sidebar-user-copy">
              <b>Data</b>
              <small>Workspace admin</small>
            </div>
            <MoreHorizontal size={17} />
          </div>
        </div>
      </aside>
      {mobileMenu && (
        <button
          className="mobile-backdrop"
          onClick={() => setMobileMenu(false)}
          aria-label="Close navigation"
        />
      )}
      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu-button"
              aria-label="Open navigation"
              onClick={() => setMobileMenu(true)}
            >
              <Menu size={19} />
            </button>
            <div className="breadcrumb">
              <span>Workspace</span>
              <ChevronRight size={13} />
              <b>{navItem?.label || "Overview"}</b>
            </div>
          </div>
          <div className="topbar-right">
            <div className="global-search-wrap">
              <div className="global-search">
                <Search size={15} />
                <input
                  aria-label="Search workspace and record pairs"
                  value={globalSearch}
                  onChange={(event) => setGlobalSearch(event.target.value)}
                  placeholder="Search workspace"
                />
                <kbd>⌘ K</kbd>
              </div>
              {globalSearch.trim() && (
                <div className="global-search-results">
                  {globalSearchResults.length ? (
                    globalSearchResults.map((result) => (
                      <button
                        key={`${result.type}-${result.id}`}
                        onClick={() => {
                          if (result.type === "page") navigate(result.id);
                          else if (result.type === "dataset")
                            navigate("datasets");
                          else if (result.type === "pair") navigate("review");
                          else if (result.type === "table") navigate("database");
                          else navigate("history");
                          setGlobalSearch("");
                        }}
                      >
                        <span>
                          {result.type === "page"
                            ? "PAGE"
                            : result.type === "dataset"
                              ? "DATASET"
                              : result.type === "pair"
                                ? "PAIR"
                                : result.type === "table"
                                  ? "TABLE"
                                : "RUN"}
                        </span>
                        <div>
                          <b>{result.title}</b>
                          <small>{result.detail}</small>
                        </div>
                        <ArrowUpRight size={14} />
                      </button>
                    ))
                  ) : (
                    <div className="search-empty">
                      No workspace results for “{globalSearch}”
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              className="icon-button theme-toggle"
              aria-label={
                dark ? "Switch to light theme" : "Switch to dark theme"
              }
              onClick={() => setDark((value) => !value)}
              title="Toggle theme"
            >
              {dark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <div className="topbar-separator" />
            <div className="notification-wrap">
              <button
                className="icon-button notification-button"
                aria-label="Open notifications"
                onClick={() => setShowNotifications((value) => !value)}
              >
                <Bell size={17} />
                <i />
              </button>
              {showNotifications && (
                <div className="notification-popover">
                  <b>Notifications</b>
                  <p>
                    <span />{" "}
                    {liveStats
                      ? liveStats.review.toLocaleString() +
                        " pairs awaiting review"
                      : "Review count unavailable"}
                  </p>
                  <p>
                    <span />{" "}
                    {reviewSummary?.last_reviewed_at
                      ? `Last audit: ${new Date(reviewSummary.last_reviewed_at).toLocaleString()}`
                      : "No audit decision recorded"}
                  </p>
                  <button onClick={() => setShowNotifications(false)}>
                    Close
                  </button>
                </div>
              )}
            </div>
            <div className="top-user">
              <span className="user-avatar small">DA</span>
              <div>
                <b>Data</b>
                <small>Admin</small>
              </div>
              <ChevronDown size={13} />
            </div>
          </div>
        </header>
        <div className="content-area">
          {renderPage()}
          <footer className="app-footer">
            <span>© 2026 HyperData Intelligence</span>
            <span className="footer-center">
              <i />{" "}
              {liveState === "live"
                ? "API connected via /api proxy"
                : liveState === "offline"
                  ? `Backend unavailable: ${liveError}`
                  : "Connecting…"}
            </span>
            <span>Platform UI · v1.1</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div className="toast">
          <CheckCircle2 size={16} />
          <span>{toast}</span>
          <button onClick={() => setToast("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {showSourceModal && (
        <div
          className="modal-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowSourceModal(false);
          }}
        >
          <div className="modal-card">
            <div className="modal-header">
              <div>
                <span className="section-kicker">DATA CONNECTOR</span>
                <h2>Add a database connection</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setShowSourceModal(false)}
              >
                <X size={17} />
              </button>
            </div>
            <p className="modal-copy">
              Create a connection profile. This prototype does not store
              credentials or establish a live database connection.
            </p>
            <Field label="Connection name">
              <input
                value={connectionName}
                onChange={(event) => setConnectionName(event.target.value)}
              />
            </Field>
            <Field label="Database engine">
              <select
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value)}
              >
                <option>PostgreSQL</option>
                <option>DuckDB</option>
              </select>
            </Field>
            <div className="form-grid">
              <Field label="Host">
                <input placeholder="localhost" />
              </Field>
              <Field label="Port">
                <input placeholder="5432" />
              </Field>
              <Field label="Database">
                <input placeholder="analytics" />
              </Field>
              <Field label="Username">
                <input placeholder="database user" autoComplete="off" />
              </Field>
            </div>
            <div className="security-callout">
              <ShieldCheck size={16} /> Actual credentials must be provided
              through a secure backend configuration, not this browser form.
            </div>
            <div className="modal-actions">
              <Button onClick={() => setShowSourceModal(false)}>Cancel</Button>
              <Button
                variant="primary"
                onClick={() => {
                  setShowSourceModal(false);
                  flash(
                    `${connectionName} saved as a local placeholder. No connection was made.`,
                  );
                }}
              >
                Save placeholder
              </Button>
            </div>
          </div>
        </div>
      )}
      {mappingOpen && mappingPreview && (
        <div
          className="modal-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setMappingOpen(false);
          }}
        >
          <div className="modal-card wide-modal">
            <div className="modal-header">
              <div>
                <span className="section-kicker">COLUMN MAPPING</span>
                <h2>Map source columns</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setMappingOpen(false)}
                aria-label="Close column mapping"
              >
                <X size={17} />
              </button>
            </div>
            <p className="modal-copy">
              {mappingPreview.file.name} · {mappingPreview.rows} rows · map
              source fields to the fields the model expects. Leave a field
              unchanged to keep its original name.
            </p>
            <div className="mapping-table">
              {mappingPreview.columns.map((column) => (
                <div className="mapping-row" key={column}>
                  <span className="mapping-source">{column}</span>
                  <ArrowRight size={14} />
                  <select
                    aria-label={`Target for ${column}`}
                    value={mappingPreview.mapping[column] || ''}
                    onChange={(event) =>
                      setMappingPreview((current) => {
                        const mapping = { ...current.mapping }
                        if (event.target.value) mapping[column] = event.target.value
                        else delete mapping[column]
                        return { ...current, mapping }
                      })
                    }
                  >
                    <option value="">Keep as-is</option>
                    {mappingPreview.targets.map((target) => (
                      <option key={target} value={target}>{target}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            <div className="modal-actions">
              <Button onClick={() => setMappingOpen(false)}>Cancel</Button>
              <Button variant="primary" disabled={mappingBusy} onClick={confirmMapping}>
                {mappingBusy ? 'Uploading…' : 'Upload dataset'}
              </Button>
            </div>
          </div>
        </div>
      )}
      {showModelModal && (
        <div
          className="modal-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowModelModal(false);
          }}
        >
          <div className="modal-card">
            <div className="modal-header">
              <div>
                <span className="section-kicker">MODEL REGISTRY</span>
                <h2>Register a processing engine</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setShowModelModal(false)}
              >
                <X size={17} />
              </button>
            </div>
            <p className="modal-copy">
              Create a metadata entry. A compatible backend adapter is required
              before the engine can be executed.
            </p>
            <Field label="Model / engine name">
              <input
                value={modelName}
                onChange={(event) => setModelName(event.target.value)}
                placeholder="e.g. Customer risk scoring"
              />
            </Field>
            <Field label="Processing family">
              <select defaultValue="Custom processing engine">
                <option>Custom processing engine</option>
                <option>Classification</option>
                <option>Regression</option>
                <option>Clustering</option>
                <option>Entity resolution</option>
                <option>Anomaly detection</option>
              </select>
            </Field>
            <div className="security-callout">
              <Code2 size={16} /> The registry entry is local only. Runtime
              loading and validation belong to FastAPI.
            </div>
            <div className="modal-actions">
              <Button onClick={() => setShowModelModal(false)}>Cancel</Button>
              <Button variant="primary" onClick={addModel}>
                Create registry entry
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TargetIcon(props) { return <Gauge {...props}/> }

export default App
