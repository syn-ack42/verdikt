import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import DimensionEditor from './DimensionEditor'
import ModelPickerTable from './ModelPickerTable'
import type { Project, RatingDimension } from '../api/types'

interface Props {
  project: Project
  onClose: () => void
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text)',
  fontSize: 14,
  boxSizing: 'border-box',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  marginBottom: 6,
  color: 'var(--text-muted)',
}

const fieldStyle: React.CSSProperties = {
  marginBottom: 20,
}

export default function ProjectSettingsDialog({ project, onClose }: Props) {
  const { data: ratings } = useQuery({
    queryKey: ['ratings', project.id],
    queryFn: () => api.ratings.list(project.id),
  })
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [threshold, setThreshold] = useState(project.crystallisation_threshold)
  const [chunkMin, setChunkMin] = useState(project.chunk_min_size)
  const [chunkMax, setChunkMax] = useState(project.chunk_max_size)
  const [dims, setDims] = useState<RatingDimension[]>(project.rating_dimensions)
  const [llmModel, setLlmModel] = useState(project.llm_model ?? '')
  const [llmKeySource, setLlmKeySource] = useState<string | null>(project.llm_key_source ?? null)
  const [embModel, setEmbModel] = useState(project.embedding_model ?? '')
  const [embKeySource, setEmbKeySource] = useState<string | null>(project.embedding_key_source ?? null)
  const [embChanged, setEmbChanged] = useState(false)
  const [judgeTemp, setJudgeTemp] = useState<string>(
    project.judge_temperature != null ? String(project.judge_temperature) : ''
  )

  const isImage = project.domain === 'image'

  const originalNames = project.rating_dimensions.map(d => d.name)
  const originalDescriptions = project.rating_dimensions.map(d => d.description)
  const ratedNames = new Set((ratings ?? []).flatMap(r => Object.keys(r.dimension_scores)))

  const { data: modelDefaults } = useQuery({
    queryKey: ['model-defaults'],
    queryFn: () => api.models.defaults(),
  })
  const { data: projectDefaults } = useQuery({
    queryKey: ['projects', 'defaults'],
    queryFn: () => api.projects.defaults(),
  })

  const rangeMin = projectDefaults?.chunk_size_min_lower ?? 0
  const rangeMax = projectDefaults?.chunk_size_max_upper ?? 1000

  const { data: veniceKeyStatus } = useQuery({
    queryKey: ['venice-key-status'],
    queryFn: () => api.auth.veniceKeyStatus(),
  })
  const { data: openRouterKeyStatus } = useQuery({
    queryKey: ['openrouter-key-status'],
    queryFn: () => api.auth.openRouterKeyStatus(),
  })
  const hasPersonalKey = (veniceKeyStatus?.configured || openRouterKeyStatus?.configured) ?? false

  const { data: llmModels } = useQuery({
    queryKey: ['models', 'llm', project.domain, hasPersonalKey],
    queryFn: () => api.models.list('llm', project.domain, hasPersonalKey),
  })
  const { data: embModels } = useQuery({
    queryKey: ['models', 'embedding', project.domain, hasPersonalKey],
    queryFn: () => api.models.list('embedding', project.domain, hasPersonalKey),
    enabled: !isImage,
  })

  const defaultLlm = modelDefaults?.llm_by_domain?.[project.domain] ?? null

  const selectedLlmModel = (llmModels ?? []).find(m => m.id === (llmModel || defaultLlm))
  const selectedEmbModel = (embModels ?? []).find(m => m.id === embModel)
  const selectedLlmIsPersonal = llmKeySource === 'personal'
  const selectedEmbIsPersonal = embKeySource === 'personal'

  const deleteProject = useMutation({
    mutationFn: () => api.projects.delete(project.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate('/')
    },
  })

  const save = useMutation({
    mutationFn: () => {
      const renames: Record<string, string> = {}
      dims.forEach((d, i) => {
        const orig = originalNames[i]
        if (orig && d.name !== orig) renames[orig] = d.name
      })
      return api.projects.update(project.id, {
        name,
        description: description || undefined,
        rating_dimensions: dims,
        crystallisation_threshold: threshold,
        ...(isImage ? {} : { chunk_min_size: chunkMin, chunk_max_size: chunkMax }),
        llm_model: llmModel || undefined,
        embedding_model: embModel || undefined,
        llm_key_source: llmKeySource,
        embedding_key_source: embKeySource,
        ...(judgeTemp === '' ? { clear_judge_temperature: true } : { judge_temperature: parseFloat(judgeTemp) }),
        ...(Object.keys(renames).length > 0 ? { dimension_renames: renames } : {}),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects', project.id] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      onClose()
    },
  })

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)',
        color: 'var(--text)',
        borderRadius: 10,
        width: 'min(680px, 94vw)',
        maxHeight: '88vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Project Settings</h3>
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>{project.name}</p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', lineHeight: 1, padding: '4px 6px' }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          <form id="settings-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>

            <div style={fieldStyle}>
              <label style={labelStyle}>Name</label>
              <input required value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
            </div>

            <div style={fieldStyle}>
              <label style={labelStyle}>Description</label>
              <input value={description} onChange={e => setDescription(e.target.value)} style={inputStyle} placeholder="Optional" />
            </div>

            {/* Numeric settings */}
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 20 }}>
              <div>
                <label style={labelStyle}>Crystallisation threshold</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="number" min={1} value={threshold}
                    onChange={e => setThreshold(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>ratings</span>
                </div>
              </div>
              {!isImage && (
                <div>
                  <label style={labelStyle}>Chunk size</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMin}
                      onChange={e => setChunkMin(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                    <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>–</span>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMax}
                      onChange={e => setChunkMax(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>words</span>
                  </div>
                </div>
              )}
            </div>

            {/* Models */}
            <div style={{ marginBottom: 20 }}>
              <label style={labelStyle}>Language model</label>
              <ModelPickerTable
                models={llmModels ?? []}
                selectedId={llmModel || defaultLlm}
                isPersonalSelected={selectedLlmIsPersonal}
                onSelect={(id, isPersonal) => {
                  setLlmModel(id ?? '')
                  setLlmKeySource(isPersonal ? 'personal' : null)
                }}
                listMaxHeight={280}
              />
              {selectedLlmModel?.source === 'venice' && (
                <p style={{ margin: '6px 0 0', fontSize: 12, color: '#7c3aed', lineHeight: 1.4 }}>
                  {selectedLlmIsPersonal
                    ? 'Venice.ai — costs charged to your personal account.'
                    : 'Venice.ai — costs charged via site key.'}
                </p>
              )}
            </div>

            {!isImage && (
              <div style={{ marginBottom: 20 }}>
                <label style={labelStyle}>Embedding model</label>
                <ModelPickerTable
                  models={embModels ?? []}
                  selectedId={embModel || null}
                  isPersonalSelected={selectedEmbIsPersonal}
                  onSelect={(id, isPersonal) => {
                    const newEmb = id ?? ''
                    setEmbModel(newEmb)
                    setEmbKeySource(isPersonal ? 'personal' : null)
                    setEmbChanged(
                      newEmb !== (project.embedding_model ?? '') ||
                      (isPersonal ? 'personal' : null) !== (project.embedding_key_source ?? null)
                    )
                  }}
                  noneLabel="Bundled default (sentence-transformers)"
                  listMaxHeight={240}
                />
                {embChanged && (
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: '#b45309', lineHeight: 1.4 }}>
                    Changing the embedding model invalidates existing vectors — re-run the pipeline after saving.
                  </p>
                )}
                {selectedEmbModel?.source === 'venice' && (
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: '#7c3aed', lineHeight: 1.4 }}>
                    {selectedEmbIsPersonal
                      ? 'Venice.ai — costs charged to your personal account.'
                      : 'Venice.ai — costs charged via site key.'}
                  </p>
                )}
              </div>
            )}

            {/* Advanced */}
            <details style={{ marginBottom: 20 }}>
              <summary style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', cursor: 'pointer', userSelect: 'none' }}>
                Advanced
              </summary>
              <div style={{ marginTop: 14 }}>
                <label style={labelStyle}>AI scoring temperature</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <input
                    type="number" min={0} max={2} step={0.05}
                    value={judgeTemp}
                    placeholder="default (0.2)"
                    onChange={e => setJudgeTemp(e.target.value)}
                    style={{ ...inputStyle, width: 120 }}
                  />
                  {judgeTemp !== '' && (
                    <button type="button" onClick={() => setJudgeTemp('')}
                      style={{ fontSize: 12, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                      reset to default
                    </button>
                  )}
                </div>
                <p style={{ margin: '5px 0 0', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  Controls how decisive the AI scorer is (0 = deterministic, 1 = creative). Lower values follow the scoring rubric more strictly and reduce score inflation. Leave blank to use the server default.
                </p>
              </div>
            </details>

            {/* Dimensions */}
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Rating Dimensions</label>
              <DimensionEditor
                dimensions={dims}
                onChange={setDims}
                originalNames={originalNames}
                originalDescriptions={originalDescriptions}
                ratedNames={ratedNames}
              />
            </div>
          </form>

          {/* Danger zone */}
          <div style={{ marginTop: 28, padding: '16px', borderRadius: 7, border: '1px solid rgba(200,0,0,0.2)', background: 'rgba(200,0,0,0.04)' }}>
            <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 700, color: '#c00' }}>Danger zone</p>
            <button
              type="button"
              onClick={() => confirm(`Permanently delete "${project.name}" and all its data?`) && deleteProject.mutate()}
              disabled={deleteProject.isPending}
              style={{
                padding: '7px 16px',
                border: '1px solid #c00',
                borderRadius: 6,
                color: '#c00',
                background: 'none',
                cursor: deleteProject.isPending ? 'default' : 'pointer',
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              {deleteProject.isPending ? 'Deleting…' : 'Delete project'}
            </button>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 20px',
          borderTop: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
          gap: 8,
        }}>
          <div style={{ flex: 1 }}>
            {save.error && (
              <span style={{ fontSize: 13, color: '#c00' }}>{String(save.error)}</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 18px',
                background: 'none',
                border: '1px solid var(--border)',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              form="settings-form"
              disabled={save.isPending}
              style={{
                padding: '8px 20px',
                background: '#6b7de0',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: save.isPending ? 'default' : 'pointer',
                fontSize: 14,
                fontWeight: 600,
                opacity: save.isPending ? 0.7 : 1,
              }}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
