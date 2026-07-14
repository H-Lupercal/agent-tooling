# Architecture and safety boundary

Install Rehearsal has five explicit stages:

1. Build a platform-specific environment overlay for a new disposable profile.
2. Snapshot that profile with bounded, descriptor-relative traversal where supported.
3. Run trusted argv directly with time, process-tree, and streaming output bounds.
4. Snapshot again and generate a canonical, redacted receipt.
5. Persist the receipt atomically, then clean the profile and its recovery marker.

`profiles.py` owns Linux, macOS, and Windows path redirection. `runner.py` owns process
execution and termination. `snapshot.py` owns filesystem observation. `models.py` and
`store.py` own the stable schema and persistence. `cli.py` composes those modules but
does not weaken their checks.

On POSIX, snapshots use directory descriptors, no-follow opens, and inode/device
revalidation. On Windows, the runner owns the installer tree through a kill-on-close Job
Object and quiesces it before the platform's path-based snapshot fallback begins.

The redirected user profile is deliberately not described as a sandbox. An installer
can still access the real filesystem, network, OS services, other processes, registries,
and any environment or credential sources the operating system exposes independently.
