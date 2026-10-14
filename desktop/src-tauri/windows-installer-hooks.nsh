!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping running opencode-haha sidecars..."
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar-x86_64-pc-windows-msvc.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar-aarch64-pc-windows-msvc.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar.exe'
  Pop $0
  Sleep 1000
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping running opencode-haha processes..."
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-desktop.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar-x86_64-pc-windows-msvc.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar-aarch64-pc-windows-msvc.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /T /IM opencode-haha-sidecar.exe'
  Pop $0
  Sleep 1000
!macroend
