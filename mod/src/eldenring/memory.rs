//! Memory reading utilities for Windows process memory access
//!
//! Provides the MemoryReader trait with default implementations for reading
//! primitive types from process memory using Windows APIs.

use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Diagnostics::Debug::ReadProcessMemory;

/// Common memory reading utilities for process memory access
///
/// Provides default implementations for reading u32, u64 (pointer), and bool
/// values from process memory. Implementors only need to provide `proc()`.
pub trait MemoryReader {
    /// Returns the process handle for memory operations
    fn proc(&self) -> HANDLE;

    /// Read a u32 from the given address
    fn read_u32(&self, addr: usize) -> Option<u32> {
        if addr == 0 {
            return None;
        }
        let mut value: u32 = 0;
        unsafe {
            ReadProcessMemory(
                self.proc(),
                addr as _,
                &mut value as *mut _ as _,
                std::mem::size_of::<u32>(),
                None,
            )
            .ok()
            .map(|_| value)
        }
    }

    /// Read a pointer (u64) from the given address
    fn read_ptr(&self, addr: usize) -> Option<usize> {
        if addr == 0 {
            return None;
        }
        let mut value: u64 = 0;
        unsafe {
            ReadProcessMemory(
                self.proc(),
                addr as _,
                &mut value as *mut _ as _,
                std::mem::size_of::<u64>(),
                None,
            )
            .ok()
            .map(|_| value as usize)
        }
    }

    /// Read a bool (u8) from the given address
    fn read_bool(&self, addr: usize) -> Option<bool> {
        if addr == 0 {
            return None;
        }
        let mut value: u8 = 0;
        unsafe {
            ReadProcessMemory(
                self.proc(),
                addr as _,
                &mut value as *mut _ as _,
                std::mem::size_of::<u8>(),
                None,
            )
            .ok()
            .map(|_| value != 0)
        }
    }
}
