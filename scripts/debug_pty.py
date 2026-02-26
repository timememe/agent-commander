"""Diagnostic script: test PTY backends for each agent directly."""

import os
import sys
import time

def test_agent(agent_key: str, command: str) -> None:
    print(f"\n{'='*60}")
    print(f"Testing: {agent_key} ({command})")
    print(f"{'='*60}")

    # 1. Check command exists
    import shutil
    resolved = shutil.which(command.split()[0])
    if not resolved:
        print(f"  [FAIL] Command '{command}' not found in PATH")
        return
    print(f"  [OK] Command found: {resolved}")

    # 2. Try PTY backend
    from agent_commander.providers.runtime.backend import build_backend
    try:
        backend = build_backend(command=command, cols=120, rows=40)
        print(f"  [OK] PTY backend created: {type(backend).__name__}")
    except Exception as e:
        print(f"  [FAIL] PTY backend failed: {e}")
        return

    # 3. Read output for 10 seconds
    print(f"  Reading PTY output for 10 seconds...")
    total_bytes = 0
    chunks = []
    start = time.time()
    while time.time() - start < 10:
        data = backend.read()
        if data:
            total_bytes += len(data)
            chunks.append(data)
            # Print first few chunks
            if len(chunks) <= 5:
                preview = repr(data[:200])
                print(f"    chunk[{len(chunks)}] ({len(data)} bytes): {preview}")
        time.sleep(0.05)

    print(f"  Total chunks: {len(chunks)}, total bytes: {total_bytes}")

    if not chunks:
        print(f"  [WARN] No output received from PTY in 10 seconds!")
        backend.close()
        return

    # 4. Test pyte rendering
    try:
        import pyte
        screen = pyte.HistoryScreen(120, 40, history=5000)
        screen.set_mode(pyte.modes.LNM)
        stream = pyte.Stream(screen)
        for chunk in chunks:
            stream.feed(chunk)
        display = "\n".join(line.rstrip() for line in screen.display if line.strip())
        print(f"\n  pyte rendered ({len(display)} chars):")
        for line in display.splitlines()[:15]:
            print(f"    | {line}")
    except ImportError:
        print(f"  [WARN] pyte not installed, skipping render test")

    # 5. Test ANSI stripping
    from agent_commander.providers.runtime.session import ANSI_FULL_RE
    raw_text = "".join(chunks)
    clean = ANSI_FULL_RE.sub("", raw_text)
    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
    clean = "".join(ch for ch in clean if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    print(f"\n  ANSI-stripped text ({len(clean)} chars):")
    for line in clean.splitlines()[:15]:
        if line.strip():
            print(f"    | {line}")

    # 6. Test prompt detection
    from agent_commander.providers.runtime.registry import get_agent_def
    import re
    agent_def = get_agent_def(agent_key)
    prompt_regexes = [re.compile(p, re.MULTILINE) for p in agent_def.prompt_patterns]
    tail = "\n".join(clean.splitlines()[-8:])
    prompt_found = any(r.search(tail) for r in prompt_regexes)
    print(f"\n  Prompt detection: {'[OK] FOUND' if prompt_found else '[WARN] NOT FOUND'}")
    print(f"  Tail (last 8 lines):")
    for line in tail.splitlines():
        print(f"    | {repr(line)}")

    # 7. Test marker extraction
    from agent_commander.providers.runtime.markers import MarkerExtractor
    extractor = MarkerExtractor(agent_key)
    extracted = extractor.feed(clean)
    flushed = extractor.flush()
    marker_result = (extracted + flushed).strip()
    print(f"\n  Marker extractor state: {extractor.state.name}")
    print(f"  has_start_marker: {extractor.has_start_marker}")
    print(f"  Extracted ({len(marker_result)} chars): {repr(marker_result[:200])}")

    backend.close()
    print(f"\n  Done.")


if __name__ == "__main__":
    # Add project to path
    sys.path.insert(0, os.path.dirname(__file__))

    agents = {
        "claude": "claude",
        "gemini": "gemini",
        "codex": "codex",
    }

    # Override from env if set
    from agent_commander.providers.runtime.registry import AGENT_DEFS
    for key, agent_def in AGENT_DEFS.items():
        cmd = agent_def.resolve_command()
        agents[key] = cmd

    # Test specific agent or all
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        if target in agents:
            test_agent(target, agents[target])
        else:
            print(f"Unknown agent: {target}. Use: {', '.join(agents)}")
    else:
        for key, cmd in agents.items():
            test_agent(key, cmd)
