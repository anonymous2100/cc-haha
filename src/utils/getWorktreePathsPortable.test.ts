import { describe, expect, mock, test } from 'bun:test'
import { promisify } from 'util'

const capturedOptions: Array<Record<string, unknown>> = []

const execFileMock = Object.assign(
  (
    _cmd: string,
    _args: string[],
    _options: Record<string, unknown>,
    callback: (err: Error | null, stdout: string) => void,
  ) => {
    capturedOptions.push(_options)
    callback(null, 'worktree D:/repo\nHEAD abc\nworktree D:/repo-wt\n')
  },
  {
    // Mirror Node's execFile custom promisify contract (resolves {stdout, stderr})
    [promisify.custom]: (
      _cmd: string,
      _args: string[],
      options: Record<string, unknown>,
    ) => {
      capturedOptions.push(options)
      return Promise.resolve({
        stdout: 'worktree D:/repo\nHEAD abc\nworktree D:/repo-wt\n',
        stderr: '',
      })
    },
  },
)

mock.module('child_process', () => ({ execFile: execFileMock }))

const { getWorktreePathsPortable } = await import('./getWorktreePathsPortable.js')

describe('getWorktreePathsPortable', () => {
  test('spawns git with windowsHide so no console window flashes on Windows', async () => {
    capturedOptions.length = 0
    await getWorktreePathsPortable('D:/repo')
    expect(capturedOptions.length).toBeGreaterThan(0)
    expect(capturedOptions.at(-1)?.windowsHide).toBe(true)
    expect(capturedOptions.at(-1)?.timeout).toBe(5000)
  })

  test('parses worktree lines from git output', async () => {
    const paths = await getWorktreePathsPortable('D:/repo')
    expect(paths).toEqual(['D:/repo', 'D:/repo-wt'])
  })
})
