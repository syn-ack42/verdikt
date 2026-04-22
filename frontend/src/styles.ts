import type React from 'react'

/** Inner container for modal dialogs — apply width/maxHeight separately per modal. */
export const modalChrome: React.CSSProperties = {
  background: 'var(--modal-bg)',
  color: 'var(--text)',
  borderRadius: 10,
  boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
  border: '1px solid var(--border)',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
}

/** Square icon button — no border, centred content, 2.4em × 2.4em. */
export const iconBtn: React.CSSProperties = {
  width: '2.4em',
  height: '2.4em',
  padding: 0,
  border: 'none',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: '1.1em',
}

/** Consistent base for text inputs and textareas. */
export const inputBase: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  padding: '6px 8px',
  boxSizing: 'border-box',
  fontFamily: 'inherit',
  fontSize: 'inherit',
}
