// [2026-11-11 T-024] Addon Forge pane for Hermes Desktop.
// Invariants:
//   1. Imports only @hermes/plugin-sdk, react, and react/jsx-runtime.
//   2. No JSX syntax. The file is loaded uncompiled.
//   3. Theme variables only. No host DOM queries. No native bridge.
//   4. Buttons call the plugin backend: status, addons, check, install, bridge pull, errors.

import { PANES_AREA, haptic } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

function line(label, value) {
  return jsxs('div', {
    className: 'text-sm text-(--ui-text-secondary)',
    children: [label, ': ', value == null || value === '' ? '—' : String(value)]
  })
}

function Section(props) {
  return jsxs('section', {
    className: 'flex flex-col gap-2 border-b border-(--ui-border) pb-3',
    children: [
      jsx('h2', { className: 'text-sm font-medium text-(--ui-text)', children: props.title }),
      props.children
    ]
  })
}

function ForgePane(props) {
  const ctx = props.ctx
  const [status, setStatus] = useState(null)
  const [addons, setAddons] = useState([])
  const [check, setCheck] = useState(null)
  const [errors, setErrors] = useState(null)
  const [bridge, setBridge] = useState(null)
  const [path, setPath] = useState('')
  const [note, setNote] = useState('')

  async function call(label, pathName, options) {
    haptic('tap')
    setNote(label)
    try {
      const result = await ctx.rest(pathName, options)
      setNote('')
      return result
    } catch (err) {
      setNote(String(err && err.message ? err.message : err))
      return null
    }
  }

  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 overflow-auto p-3 text-(--ui-text)',
    children: [
      jsx(Section, {
        title: 'Game',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () => setStatus(await call('status', '/status')),
              children: 'Refresh status'
            }),
            line('flavor', status && status.flavor),
            line('build', status && status.build),
            line('interface', status && status.interface)
          ]
        })
      }),
      jsx(Section, {
        title: 'Addons',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () => {
                const result = await call('addons', '/addons')
                setAddons(result && Array.isArray(result.addons) ? result.addons : [])
              },
              children: 'List addons'
            }),
            jsx('div', {
              className: 'text-sm text-(--ui-text-secondary)',
              children: addons.length ? addons.join(', ') : '—'
            })
          ]
        })
      }),
      jsx(Section, {
        title: 'Check results',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            jsx('input', {
              className: 'rounded border border-(--ui-border) bg-transparent px-2 py-1 text-sm',
              value: path,
              placeholder: 'Addon folder path',
              onChange: (event) => setPath(event.target.value)
            }),
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () =>
                setCheck(await call('check', '/check', { method: 'POST', body: { path } })),
              children: 'Check'
            }),
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () =>
                setNote(
                  JSON.stringify(
                    await call('install', '/install', { method: 'POST', body: { path, mode: 'copy' } })
                  )
                ),
              children: 'Install'
            }),
            line('verdict', check && check.verdict),
            line('errors', check && check.error_count)
          ]
        })
      }),
      jsx(Section, {
        title: 'In-game errors',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () => setErrors(await call('errors', '/errors')),
              children: 'Read errors'
            }),
            line('count', errors && (errors.count != null ? errors.count : errors.error_count))
          ]
        })
      }),
      jsx(Section, {
        title: 'Bridge',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            jsx('button', {
              type: 'button',
              className: 'w-fit rounded px-2 py-1 text-sm',
              onClick: async () =>
                setBridge(await call('bridge', '/bridge/pull', { method: 'POST', body: {} })),
              children: 'Pull outbox'
            }),
            line('records', bridge && (bridge.count != null ? bridge.count : bridge.appended))
          ]
        })
      }),
      note
        ? jsx('div', { className: 'text-sm text-(--ui-text-tertiary)', children: note })
        : null
    ]
  })
}

export default {
  id: 'wow-addon-forge',
  name: 'Addon Forge',
  register(ctx) {
    ctx.register({
      id: 'addon-forge',
      area: PANES_AREA,
      title: 'Addon Forge',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(ForgePane, { ctx })
    })
  }
}
