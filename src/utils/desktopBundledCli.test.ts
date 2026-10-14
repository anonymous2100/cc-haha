import { describe, expect, test } from 'bun:test'
import {
  buildClaudeCliArgs,
  resolveBundledCliPathFromExecPath,
  resolveClaudeCliLauncher,
} from './desktopBundledCli.js'

describe('resolveBundledCliPathFromExecPath', () => {
  test('resolves the bundled sidecar binary as the CLI', () => {
    const execPath =
      '/opt/opencode-haha/opencode-haha-sidecar-x86_64-pc-windows-msvc.exe'
    expect(resolveBundledCliPathFromExecPath(execPath)).toBe(execPath)
  })

  test('ignores executables that are not our launcher', () => {
    // Legacy Claude-named binaries are not this product's CLI; the desktop
    // shell must never spawn one on its own.
    expect(
      resolveBundledCliPathFromExecPath(
        '/opt/app/claude-server-x86_64-pc-windows-msvc.exe',
      ),
    ).toBeNull()
    expect(resolveBundledCliPathFromExecPath('/opt/app/claude-cli-2.1.0')).toBeNull()
    expect(resolveBundledCliPathFromExecPath('/opt/app/opencode-haha.exe')).toBeNull()
  })
})

describe('resolveClaudeCliLauncher', () => {
  test('classifies the sidecar binary as a sidecar that needs the app root', () => {
    const command = '/opt/opencode-haha-sidecar-aarch64-apple-darwin'
    expect(resolveClaudeCliLauncher({ cliPath: command })).toEqual({
      command,
      kind: 'sidecar',
      requiresAppRoot: true,
    })
  })

  test('classifies scripts and plain binaries', () => {
    expect(
      resolveClaudeCliLauncher({ cliPath: '/repo/bin/opencode-haha.ts' })?.kind,
    ).toBe('script')
    expect(
      resolveClaudeCliLauncher({ cliPath: '/usr/local/bin/agent' }),
    ).toEqual({
      command: '/usr/local/bin/agent',
      kind: 'binary',
      requiresAppRoot: false,
    })
  })

  test('returns null when no launcher can be resolved', () => {
    expect(
      resolveClaudeCliLauncher({
        cliPath: null,
        execPath: '/opt/app/opencode-haha.exe',
      }),
    ).toBeNull()
  })
})

describe('buildClaudeCliArgs', () => {
  const sidecar = resolveClaudeCliLauncher({
    cliPath: '/opt/opencode-haha-sidecar-x86_64-unknown-linux-gnu',
  })!

  test('passes the app root to the sidecar CLI mode', () => {
    expect(buildClaudeCliArgs(sidecar, ['-p', 'hi'], '/opt/app')).toEqual([
      '/opt/opencode-haha-sidecar-x86_64-unknown-linux-gnu',
      'cli',
      '--app-root',
      '/opt/app',
      '-p',
      'hi',
    ])
  })

  test('omits the app root when it is unknown', () => {
    expect(buildClaudeCliArgs(sidecar, ['-p'], '')).toEqual([
      '/opt/opencode-haha-sidecar-x86_64-unknown-linux-gnu',
      'cli',
      '-p',
    ])
  })

  test('runs scripts through bun and leaves plain binaries alone', () => {
    const script = resolveClaudeCliLauncher({
      cliPath: '/repo/bin/opencode-haha.ts',
    })!
    expect(buildClaudeCliArgs(script, ['--version'], '/opt/app')).toEqual([
      'bun',
      '/repo/bin/opencode-haha.ts',
      '--version',
    ])

    const binary = resolveClaudeCliLauncher({ cliPath: '/usr/local/bin/agent' })!
    expect(buildClaudeCliArgs(binary, ['--version'], '/opt/app')).toEqual([
      '/usr/local/bin/agent',
      '--version',
    ])
  })
})
