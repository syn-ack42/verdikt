import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import MarkdownView from '../components/MarkdownView'

type Section = { id: string; label: string }

const CORE_SECTIONS: Section[] = [
  { id: 'overview',       label: 'How it works' },
  { id: 'rating',         label: 'Rating' },
  { id: 'ai-rating',      label: 'AI Rating' },
  { id: 'profile',        label: 'Profile & Crystallisation' },
  { id: 'projects',       label: 'Projects & Settings' },
  { id: 'data-privacy',   label: 'Data & Privacy' },
]

// ── Core help content ──────────────────────────────────────────────────────────

function SectionOverview() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>How Verdikt works</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 16 }}>
        Verdikt learns your preferences by asking you to rate small content samples, then uses an AI model to build a structured preference profile. Your ratings, files, and preference data stay within the Verdikt instance you are connected to and are not shared with any third party. You can run Verdikt privately on your own machine or server, or use a hosted instance operated by someone you trust.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>The workflow</h3>
      <ol style={{ paddingLeft: 24, lineHeight: 2 }}>
        <li><strong>Create a project</strong> — choose a domain (text or image), define the dimensions you want to rate on (e.g. prose quality, atmosphere, composition).</li>
        <li><strong>Add content</strong> — upload files or use a source plugin (AO3, your local file storage). The project remains independent: each project has its own corpus, ratings, and profile.</li>
        <li><strong>Run the pipeline</strong> — Verdikt chunks your content into rating-sized pieces, embeds them into a vector space, and clusters them for diversity sampling.</li>
        <li><strong>Rate chunks</strong> — score representative samples using keyboard shortcuts. Early sessions prioritise variety; later sessions target the most informative chunks.</li>
        <li><strong>Crystallise</strong> — once you have enough ratings, a local LLM synthesises a structured preference profile describing what you like and why.</li>
        <li><strong>AI rating</strong> — with a profile, the AI scores remaining chunks automatically in the background. You review and confirm its guesses to build confidence.</li>
        <li><strong>Recommendations</strong> — the profile drives a two-stage recommender: fast embedding search narrows candidates, then the LLM scores each one against your profile with per-dimension explanations.</li>
      </ol>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Domains</h3>
      <p style={{ lineHeight: 1.7 }}>The domain is set when you create a project and cannot be changed afterwards.</p>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, marginTop: 8 }}>
        <thead>
          <tr>
            {['Domain', 'Embedding', 'LLM requirement', 'Chunking'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', borderBottom: '2px solid var(--border)', fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[
            ['Text', 'Sentence-transformers (bundled)', 'Any Ollama model', 'Word-count windows'],
            ['Image', 'CLIP (auto-downloaded)', 'Vision model (e.g. llava)', '1 image = 1 chunk'],
          ].map((row, i) => (
            <tr key={i}>
              {row.map((c, j) => <td key={j} style={{ padding: '6px 12px', borderBottom: '1px solid var(--border)' }}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SectionRating() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>Rating</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 12 }}>
        The rating interface shows one content chunk at a time. Score each dimension on a scale of 1–5, then submit. A session of 20–30 ratings is usually enough to feel the shape of your preferences.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Keyboard shortcuts</h3>
      <table style={{ borderCollapse: 'collapse', fontSize: 13, marginBottom: 20 }}>
        <tbody>
          {[
            ['1–5', 'Score the active dimension'],
            ['Tab / →', 'Next dimension'],
            ['Shift+Tab / ←', 'Previous dimension'],
            ['Enter', 'Submit (all dimensions must be scored)'],
            ['s', 'Skip this chunk'],
          ].map(([key, desc]) => (
            <tr key={key}>
              <td style={{ padding: '5px 16px 5px 0', fontFamily: 'monospace', fontWeight: 600, whiteSpace: 'nowrap' }}>{key}</td>
              <td style={{ padding: '5px 0', color: 'var(--text-muted)' }}>{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Rating modes</h3>
      <p style={{ lineHeight: 1.7 }}><strong>Normal mode</strong> — rates new, unrated chunks. Early in a project this uses diversity sampling (maximising cluster coverage). Once your rating count passes half the crystallisation threshold it switches to uncertainty sampling (targeting the most informative chunks for the current profile).</p>
      <p style={{ lineHeight: 1.7, marginTop: 8 }}><strong>Confirm AI mode</strong> — reviews chunks the AI has already scored. The AI's score is pre-filled; adjust any dimension before submitting. Your agreement is tracked as profile confidence.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Skipping</h3>
      <p style={{ lineHeight: 1.7 }}>Skip a chunk if it is unrateable (corrupted content, irrelevant material, etc.). Skipped chunks do not count towards the crystallisation threshold and are not included in profile training data.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Score scale</h3>
      <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
        <tbody>
          {[['1', 'Strong dislike'], ['2', 'Dislike'], ['3', 'Neutral'], ['4', 'Like'], ['5', 'Strong like']].map(([n, l]) => (
            <tr key={n}><td style={{ padding: '4px 16px 4px 0', fontWeight: 600, fontFamily: 'monospace' }}>{n}</td><td style={{ color: 'var(--text-muted)' }}>{l}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SectionAIRating() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>AI Rating</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 12 }}>
        Once a preference profile exists, Verdikt can score chunks automatically in the background using the same LLM that crystallised your profile.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Starting AI rating</h3>
      <p style={{ lineHeight: 1.7 }}>Click <strong>Start AI Rating</strong> on the project dashboard. The process runs in the background — you can navigate away and return to check progress. Click <strong>Stop</strong> at any time; the current chunk finishes before the job stops.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>AI preview</h3>
      <p style={{ lineHeight: 1.7 }}>In normal rating mode, as soon as you open a new chunk the AI scores it in the background. After you submit your own score, a flash bar shows what the AI would have rated and how closely the scores matched. This match rate feeds directly into profile confidence.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Profile confidence (AI accuracy)</h3>
      <p style={{ lineHeight: 1.7 }}>
        The confidence percentage shown on the dashboard is prediction accuracy — the average agreement between AI and human scores across confirmed chunks. Agreement per chunk = <code style={{ fontFamily: 'monospace', background: 'var(--surface, rgba(128,128,128,0.12))', padding: '1px 5px', borderRadius: 3 }}>avg(1 − |ai − you| / 4)</code> per dimension.
      </p>
      <ul style={{ paddingLeft: 24, lineHeight: 1.8, marginTop: 8 }}>
        <li><strong>≥ 90%</strong> — profile is predictive; AI and human scores agree closely</li>
        <li><strong>&lt; 90% after 5+ confirmations</strong> — an amber badge suggests re-crystallising with more ratings</li>
      </ul>
      <p style={{ lineHeight: 1.7, marginTop: 8 }}>Confidence resets with each new profile version, so you can track improvement over time.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Token usage</h3>
      <p style={{ lineHeight: 1.7 }}>Each LLM call for AI rating and preview consumes tokens. If your account has a token budget configured by an administrator, a live counter appears on the dashboard while a job is running. You can check your full token history at <strong>Settings › Token Usage</strong>.</p>
    </div>
  )
}

function SectionProfile() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>Profile & Crystallisation</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 12 }}>
        A preference profile is a structured description of your tastes — one summary per rating dimension plus an overall narrative. It is generated by a local LLM from your rated chunks and drives both AI scoring and recommendations.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Crystallising</h3>
      <p style={{ lineHeight: 1.7 }}>Open the <strong>Profile</strong> tab and click <strong>Crystallise</strong>. The dashboard badge shows progress and a live token counter. Crystallisation is synchronous — the page stays open while it runs (typically 1–2 minutes depending on model speed and number of dimensions).</p>
      <p style={{ lineHeight: 1.7, marginTop: 8 }}>The project's <strong>crystallisation threshold</strong> sets the minimum number of non-skipped ratings required. Once you hit it the profile button becomes active. You can re-crystallise at any time; each run creates a new profile version, preserving the history.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>What the profile contains</h3>
      <ul style={{ paddingLeft: 24, lineHeight: 1.8 }}>
        <li><strong>Per-dimension summary</strong> — a 2–4 sentence description of what you like and dislike about each dimension, derived from your top and bottom-scoring examples</li>
        <li><strong>Overall summary</strong> — a 3–5 sentence narrative integrating all dimensions</li>
        <li><strong>Typical scores</strong> — the mean of your ratings per dimension, used as fallback scores when AI parsing fails</li>
      </ul>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Editing and restoring</h3>
      <p style={{ lineHeight: 1.7 }}>You can edit any dimension summary or the overall narrative directly in the Profile view. Saves create a new version. Previous versions can be restored from the version history panel.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Re-crystallising</h3>
      <p style={{ lineHeight: 1.7 }}>Re-crystallise when: you have added significantly more ratings, the amber confidence badge appears, or you feel the profile no longer reflects your current tastes. Each re-crystallisation uses all non-skipped ratings accumulated to date.</p>
    </div>
  )
}

function SectionProjects() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>Projects & Settings</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 12 }}>
        Each project is fully isolated — its own corpus, ratings, profile, and recommendations. Settings are accessible via the gear icon on the project dashboard.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Rating dimensions</h3>
      <p style={{ lineHeight: 1.7 }}>Dimensions are the axes you rate on. You define them when creating a project and can add, remove, or rename them later. When you rename a dimension, existing ratings are migrated to the new name automatically. Changing the <em>meaning</em> of a dimension by editing its description may invalidate older ratings — a warning is shown when existing ratings exist for a dimension you're editing.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Crystallisation threshold</h3>
      <p style={{ lineHeight: 1.7 }}>The minimum number of non-skipped ratings required before crystallisation. Lower values give faster but less reliable profiles. The system default can be adjusted by an administrator via <code style={{ fontFamily: 'monospace', background: 'var(--surface, rgba(128,128,128,0.12))', padding: '1px 5px', borderRadius: 3 }}>VERDIKT_DEFAULT_CRYSTALLISATION_THRESHOLD</code>.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Chunk size (text projects)</h3>
      <p style={{ lineHeight: 1.7 }}>Controls how many words each rating chunk contains. Smaller chunks let you rate more precisely; larger chunks give more context per rating. The allowed range is set server-wide by the administrator. Changing chunk size after running the pipeline requires re-running the pipeline to re-chunk existing works.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Language model</h3>
      <p style={{ lineHeight: 1.7 }}>The LLM used for crystallisation, AI rating, and recommendations. Defaults to the server-wide default for your domain (set by the admin in <strong>Admin › Models</strong>). You can override it per-project to test different models.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Embedding model (text projects)</h3>
      <p style={{ lineHeight: 1.7 }}>The model used to embed chunks into the vector space. The bundled default is <code style={{ fontFamily: 'monospace', background: 'var(--surface, rgba(128,128,128,0.12))', padding: '1px 5px', borderRadius: 3 }}>all-MiniLM-L6-v2</code>. Changing this after the pipeline has run requires re-running the pipeline to re-embed all works; ratings and profiles are preserved.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Export and import</h3>
      <p style={{ lineHeight: 1.7 }}>Export a project as JSON from the project list (three-dot menu). The export contains all metadata, ratings, and profiles — but not binary content (images, large files). On import, materials are marked as ingested and need the pipeline re-run to regenerate chunks and embeddings.</p>
    </div>
  )
}

function SectionDataPrivacy() {
  return (
    <div>
      <h2 style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>Data & Privacy</h2>
      <p style={{ lineHeight: 1.7, marginBottom: 12 }}>
        Your preference data, ratings, and uploaded files stay within the Verdikt instance you are using and are not shared with any third party. You can run Verdikt entirely on your own machine for maximum privacy, or use a hosted instance — in either case the data boundary is the server, not an external cloud.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Per-user encryption</h3>
      <p style={{ lineHeight: 1.7 }}>Your database is encrypted at rest using SQLCipher (AES-256 CBC). The encryption key is derived from your password using Argon2id and is embedded in your login cookie for the duration of your session. It is never stored on disk. If you forget your password, your data cannot be recovered.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>File encryption</h3>
      <p style={{ lineHeight: 1.7 }}>Uploaded files are stored as opaque encrypted blobs (AES-256-GCM). On disk they have UUID names with no extension or readable metadata. Only your database maps them back to filenames and paths. A server administrator cannot read your files or determine what you have uploaded.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>AI inference</h3>
      <p style={{ lineHeight: 1.7 }}>All LLM calls go to an Ollama instance running on the same server as Verdikt. Content is necessarily passed to the model for processing, but it never leaves the server. No content is sent to any external cloud service. Support for remote model providers is not yet available; when it is, such models will be clearly labelled and privacy-first providers will be preferred.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>What is not sealed at rest</h3>
      <p style={{ lineHeight: 1.7 }}>
        The embedding database (ChromaDB) does not support encryption and remains unencrypted on disk. It contains only numerical vectors and opaque internal IDs — no filenames, no text, no usernames. Reconstructing readable content from raw embedding vectors requires reversing the neural network that produced them; this is not a realistic attack for the models Verdikt uses.
      </p>
      <p style={{ lineHeight: 1.7, marginTop: 8 }}>
        For deployments where even this exposure is unacceptable, full-disk encryption at the OS level (e.g. LUKS on Linux) is the appropriate control.
      </p>
      <p style={{ lineHeight: 1.7, marginTop: 8 }}>
        Verdikt does not log content, filenames, URLs, or email addresses. Log output contains only counts, status codes, UUIDs, and error messages.
      </p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Data location</h3>
      <table style={{ borderCollapse: 'collapse', fontSize: 13, marginTop: 8, width: '100%' }}>
        <tbody>
          {[
            ['Your database', 'VERDIKT_USERS_DIR/<user-id>/verdikt.db', 'SQLCipher encrypted'],
            ['Vector store', 'VERDIKT_USERS_DIR/<user-id>/chroma/', 'Plain ChromaDB'],
            ['Uploaded files', 'VERDIKT_USERS_DIR/<user-id>/files/', 'AES-256-GCM encrypted blobs'],
            ['User accounts', 'VERDIKT_DATA_DIR/auth.db', 'Plain SQLite (no ratings/content)'],
          ].map(([label, path, note]) => (
            <tr key={label} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '7px 14px 7px 0', fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</td>
              <td style={{ padding: '7px 14px', fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>{path}</td>
              <td style={{ padding: '7px 0', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{note}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Changing your password</h3>
      <p style={{ lineHeight: 1.7 }}>Changing your password re-encrypts your database with a key derived from the new password. Old sessions using the previous key are immediately invalidated. Go to <strong>Settings › Change password</strong>.</p>

      <h3 style={{ margin: '20px 0 8px', fontSize: 15, fontWeight: 600 }}>Deleting your data</h3>
      <p style={{ lineHeight: 1.7 }}>An administrator can delete your account from <strong>Admin › Users</strong>. This permanently removes your encrypted database, vector store, uploaded files, token history, and account record. There is no recovery.</p>
    </div>
  )
}

// ── Plugin help section ─────────────────────────────────────────────────────

function PluginHelpSection({ pluginName }: { pluginName: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['plugin-help', pluginName],
    queryFn: () => api.plugins.help(pluginName),
  })

  if (isLoading) return <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Loading…</p>
  if (isError || !data?.markdown) return <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>No help content available for this plugin.</p>

  return <MarkdownView markdown={data.markdown} />
}

// ── Main Help page ──────────────────────────────────────────────────────────

export default function Help() {
  const navigate = useNavigate()
  const [activeId, setActiveId] = useState('overview')

  const { data: plugins } = useQuery({
    queryKey: ['plugins'],
    queryFn: () => api.plugins.list(),
  })

  const pluginSections: Section[] = (plugins ?? []).map(p => ({
    id: `plugin-${p.name}`,
    label: p.title,
  }))

  const sidebarStyle: React.CSSProperties = {
    width: 180,
    flexShrink: 0,
    borderRight: '1px solid var(--border)',
    paddingRight: 16,
  }

  const navItemStyle = (id: string): React.CSSProperties => ({
    display: 'block',
    padding: '7px 10px',
    borderRadius: 5,
    fontSize: 13,
    cursor: 'pointer',
    color: activeId === id ? '#6b7de0' : 'var(--text)',
    background: activeId === id ? 'rgba(107,125,224,0.1)' : 'none',
    fontWeight: activeId === id ? 600 : 400,
    border: 'none',
    textAlign: 'left',
    width: '100%',
    marginBottom: 2,
  })

  const renderContent = () => {
    if (activeId === 'overview')     return <SectionOverview />
    if (activeId === 'rating')       return <SectionRating />
    if (activeId === 'ai-rating')    return <SectionAIRating />
    if (activeId === 'profile')      return <SectionProfile />
    if (activeId === 'projects')     return <SectionProjects />
    if (activeId === 'data-privacy') return <SectionDataPrivacy />
    if (activeId.startsWith('plugin-')) {
      const pluginName = activeId.slice('plugin-'.length)
      const plugin = plugins?.find(p => p.name === pluginName)
      return <PluginHelpSection pluginName={pluginName} />
    }
    return null
  }

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 12px', cursor: 'pointer', fontSize: 14 }}
        >← Back</button>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Help</h1>
      </div>

      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>
        {/* Sidebar */}
        <nav style={sidebarStyle}>
          {CORE_SECTIONS.map(s => (
            <button key={s.id} style={navItemStyle(s.id)} onClick={() => setActiveId(s.id)}>{s.label}</button>
          ))}
          {pluginSections.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, color: 'var(--text-muted)', margin: '14px 0 6px 10px' }}>Plugins</div>
              {pluginSections.map(s => (
                <button key={s.id} style={navItemStyle(s.id)} onClick={() => setActiveId(s.id)}>{s.label}</button>
              ))}
            </>
          )}
        </nav>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {renderContent()}
        </div>
      </div>
    </div>
  )
}
