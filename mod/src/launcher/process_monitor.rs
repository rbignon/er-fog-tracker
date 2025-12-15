// Process monitor for Elden Ring detection and DLL injection
// Uses Windows API directly to avoid dependency on hudhook for the launcher

use std::path::PathBuf;
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use std::ffi::OsStr;
#[cfg(target_os = "windows")]
use std::os::windows::ffi::OsStrExt;

const PROCESS_NAME: &str = "eldenring.exe";
const POST_DETECTION_DELAY: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, PartialEq)]
pub enum ProcessState {
    /// Game is not running
    NotRunning,
    /// Game is running but mod not injected
    Running,
    /// Mod has been injected
    Injected,
}

#[derive(Debug)]
pub enum InjectionError {
    DllNotFound(PathBuf),
    ProcessNotFound,
    InjectionFailed(String),
    #[allow(dead_code)]
    NotSupported,
}

impl std::fmt::Display for InjectionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            InjectionError::DllNotFound(path) => {
                write!(f, "DLL not found: {}", path.display())
            }
            InjectionError::ProcessNotFound => {
                write!(f, "Elden Ring process not found")
            }
            InjectionError::InjectionFailed(msg) => {
                write!(f, "Injection failed: {}", msg)
            }
            InjectionError::NotSupported => {
                write!(f, "Injection not supported on this platform")
            }
        }
    }
}

pub struct ProcessMonitor {
    state: ProcessState,
    dll_path: PathBuf,
    detection_time: Option<Instant>,
    #[cfg(target_os = "windows")]
    process_id: Option<u32>,
}

impl ProcessMonitor {
    pub fn new(dll_path: PathBuf) -> Self {
        Self {
            state: ProcessState::NotRunning,
            dll_path,
            detection_time: None,
            #[cfg(target_os = "windows")]
            process_id: None,
        }
    }

    /// Get current process state
    pub fn state(&self) -> &ProcessState {
        &self.state
    }

    /// Check for process and update state
    /// Returns true if state changed
    pub fn poll(&mut self) -> bool {
        let old_state = self.state.clone();

        match &self.state {
            ProcessState::NotRunning => {
                if let Some(pid) = find_process_by_name(PROCESS_NAME) {
                    self.state = ProcessState::Running;
                    self.detection_time = Some(Instant::now());
                    #[cfg(target_os = "windows")]
                    {
                        self.process_id = Some(pid);
                    }
                    #[cfg(not(target_os = "windows"))]
                    {
                        let _ = pid; // suppress unused warning
                    }
                }
            }
            ProcessState::Running | ProcessState::Injected => {
                #[cfg(target_os = "windows")]
                let still_running = self
                    .process_id
                    .map(|pid| is_process_running(pid))
                    .unwrap_or(false);
                #[cfg(not(target_os = "windows"))]
                let still_running = find_process_by_name(PROCESS_NAME).is_some();

                if !still_running {
                    self.state = ProcessState::NotRunning;
                    self.detection_time = None;
                    #[cfg(target_os = "windows")]
                    {
                        self.process_id = None;
                    }
                }
            }
        }

        self.state != old_state
    }

    /// Check if the process has been running long enough to inject
    pub fn ready_to_inject(&self) -> bool {
        if self.state != ProcessState::Running {
            return false;
        }

        self.detection_time
            .map(|t| t.elapsed() >= POST_DETECTION_DELAY)
            .unwrap_or(false)
    }

    /// Time remaining before injection is ready (for UI display)
    pub fn time_until_ready(&self) -> Option<Duration> {
        if self.state != ProcessState::Running {
            return None;
        }

        self.detection_time.and_then(|t| {
            let elapsed = t.elapsed();
            if elapsed >= POST_DETECTION_DELAY {
                None
            } else {
                Some(POST_DETECTION_DELAY - elapsed)
            }
        })
    }

    /// Inject the DLL into the running process
    #[cfg(target_os = "windows")]
    pub fn inject(&mut self) -> Result<(), InjectionError> {
        if self.state != ProcessState::Running {
            return Err(InjectionError::ProcessNotFound);
        }

        if !self.dll_path.exists() {
            return Err(InjectionError::DllNotFound(self.dll_path.clone()));
        }

        let pid = self.process_id.ok_or(InjectionError::ProcessNotFound)?;

        inject_dll(pid, &self.dll_path)?;

        self.state = ProcessState::Injected;
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    pub fn inject(&mut self) -> Result<(), InjectionError> {
        Err(InjectionError::NotSupported)
    }

    /// Reset state (for when user cancels or wants to try again)
    pub fn reset(&mut self) {
        self.state = ProcessState::NotRunning;
        self.detection_time = None;
        #[cfg(target_os = "windows")]
        {
            self.process_id = None;
        }
    }
}

// =============================================================================
// Windows Process Utilities
// =============================================================================

#[cfg(target_os = "windows")]
fn find_process_by_name(name: &str) -> Option<u32> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32First, Process32Next, PROCESSENTRY32, TH32CS_SNAPPROCESS,
    };

    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;

        let mut entry = PROCESSENTRY32 {
            dwSize: std::mem::size_of::<PROCESSENTRY32>() as u32,
            ..Default::default()
        };

        if Process32First(snapshot, &mut entry).is_ok() {
            loop {
                let exe_name = std::ffi::CStr::from_ptr(entry.szExeFile.as_ptr() as *const i8)
                    .to_string_lossy();

                if exe_name.eq_ignore_ascii_case(name) {
                    let _ = CloseHandle(snapshot);
                    return Some(entry.th32ProcessID);
                }

                if Process32Next(snapshot, &mut entry).is_err() {
                    break;
                }
            }
        }

        let _ = CloseHandle(snapshot);
    }

    None
}

#[cfg(not(target_os = "windows"))]
fn find_process_by_name(_name: &str) -> Option<u32> {
    // Not supported on non-Windows
    None
}

#[cfg(target_os = "windows")]
fn is_process_running(pid: u32) -> bool {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};

    unsafe {
        if let Ok(handle) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            let _ = CloseHandle(handle);
            true
        } else {
            false
        }
    }
}

#[cfg(target_os = "windows")]
fn inject_dll(pid: u32, dll_path: &PathBuf) -> Result<(), InjectionError> {
    use windows::core::PCSTR;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::Debug::WriteProcessMemory;
    use windows::Win32::System::LibraryLoader::{GetModuleHandleA, GetProcAddress};
    use windows::Win32::System::Memory::{
        VirtualAllocEx, VirtualFreeEx, MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, PAGE_READWRITE,
    };
    use windows::Win32::System::Threading::{
        CreateRemoteThread, OpenProcess, WaitForSingleObject, PROCESS_ALL_ACCESS,
    };

    let dll_path_str = dll_path.to_string_lossy();
    let dll_path_wide: Vec<u16> = OsStr::new(&*dll_path_str)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let dll_path_bytes = dll_path_wide.len() * 2;

    unsafe {
        // Open target process
        let process = OpenProcess(PROCESS_ALL_ACCESS, false, pid)
            .map_err(|e| InjectionError::InjectionFailed(format!("OpenProcess failed: {}", e)))?;

        // Allocate memory in target process
        let remote_mem = VirtualAllocEx(
            process,
            None,
            dll_path_bytes,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        );

        if remote_mem.is_null() {
            let _ = CloseHandle(process);
            return Err(InjectionError::InjectionFailed(
                "VirtualAllocEx failed".to_string(),
            ));
        }

        // Write DLL path to target process
        let write_result = WriteProcessMemory(
            process,
            remote_mem,
            dll_path_wide.as_ptr() as *const _,
            dll_path_bytes,
            None,
        );

        if write_result.is_err() {
            let _ = VirtualFreeEx(process, remote_mem, 0, MEM_RELEASE);
            let _ = CloseHandle(process);
            return Err(InjectionError::InjectionFailed(
                "WriteProcessMemory failed".to_string(),
            ));
        }

        // Get LoadLibraryW address
        let kernel32 = GetModuleHandleA(PCSTR(b"kernel32.dll\0".as_ptr())).map_err(|e| {
            InjectionError::InjectionFailed(format!("GetModuleHandle failed: {}", e))
        })?;

        let load_library = GetProcAddress(kernel32, PCSTR(b"LoadLibraryW\0".as_ptr()))
            .ok_or_else(|| InjectionError::InjectionFailed("GetProcAddress failed".to_string()))?;

        // Create remote thread
        let thread = CreateRemoteThread(
            process,
            None,
            0,
            Some(std::mem::transmute(load_library)),
            Some(remote_mem),
            0,
            None,
        )
        .map_err(|e| {
            InjectionError::InjectionFailed(format!("CreateRemoteThread failed: {}", e))
        })?;

        // Wait for thread to complete
        WaitForSingleObject(thread, 10000);

        // Cleanup
        let _ = CloseHandle(thread);
        let _ = VirtualFreeEx(process, remote_mem, 0, MEM_RELEASE);
        let _ = CloseHandle(process);
    }

    Ok(())
}

/// Find the DLL path relative to the launcher executable
pub fn find_dll_path() -> Option<PathBuf> {
    let exe_path = std::env::current_exe().ok()?;
    let exe_dir = exe_path.parent()?;

    // Check next to the executable
    let dll_path = exe_dir.join("fog_rando_tracker.dll");
    if dll_path.exists() {
        return Some(dll_path);
    }

    // Check in current working directory
    let cwd_dll = PathBuf::from("fog_rando_tracker.dll");
    if cwd_dll.exists() {
        return Some(cwd_dll.canonicalize().ok()?);
    }

    // Check in parent directory (for development)
    let parent_dll = exe_dir.join("../fog_rando_tracker.dll");
    if parent_dll.exists() {
        return Some(parent_dll.canonicalize().ok()?);
    }

    None
}
