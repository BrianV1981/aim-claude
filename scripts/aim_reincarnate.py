#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import signal
import json

def find_aim_root():
    current = os.path.abspath(os.getcwd())
    while current != '/':
        if os.path.exists(os.path.join(current, "core/CONFIG.json")): return current
        if os.path.exists(os.path.join(current, "setup.sh")): return current
        current = os.path.dirname(current)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AIM_ROOT = find_aim_root()

def _load_handoff_config():
    """Import handoff_config from src/."""
    src_dir = os.path.join(AIM_ROOT, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from handoff_config import resolve_target_agent, get_agent_config, DEFAULT_FALLBACK_AGENT
    return resolve_target_agent, get_agent_config, DEFAULT_FALLBACK_AGENT


def main():
    print("--- A.I.M. REINCARNATION PROTOCOL ---")

    # Parse CLI args: intent text and optional --agent override
    cli_agent = None
    args = sys.argv[1:]
    intent_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--agent" and i + 1 < len(args):
            cli_agent = args[i + 1]
            i += 2
        else:
            intent_parts.append(args[i])
            i += 1

    if intent_parts:
        user_injection = " ".join(intent_parts)
        print(f"\n[!] Commander's Intent received: {user_injection}")
    else:
        print("\n[!] CONTEXT FADE DETECTED: We are initiating Reincarnation.")
        print("What is your 'Commander's Intent' for the next agent? (Your manual injection)")
        user_injection = input("Intent: ")

    # Resolve target agent
    resolve_target_agent, get_agent_config, DEFAULT_FALLBACK_AGENT = _load_handoff_config()
    config_agent = None
    try:
        config_path = os.path.join(AIM_ROOT, "core", "CONFIG.json")
        with open(config_path) as f:
            config = json.load(f)
        config_agent = config.get("reincarnation", {}).get("handoff_agent")
    except Exception:
        pass

    target_agent = resolve_target_agent(cli_agent=cli_agent, config_agent=config_agent)
    agent_cfg = get_agent_config(target_agent)
    print(f"\n[!] Target agent: {target_agent} (cmd: {agent_cfg['cmd']})")

    venv_python = os.path.join(AIM_ROOT, "venv", "bin", "python3")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    # 0. Sync issue tracker so ISSUE_TRACKER.md is fresh before the handoff is written
    print("[0/4] Syncing issue tracker from GitHub...")
    try:
        subprocess.run(
            [venv_python, os.path.join(AIM_ROOT, "scripts", "sync_issue_tracker.py")],
            cwd=AIM_ROOT, check=True, timeout=15
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[WARN] Issue tracker sync failed (non-fatal): {e}")

    # 0.5. Run scrivener pipeline (T1 session summarizer + System 1 history_scribe)
    # Fired here — at the definitive session boundary — so the JSONL is unambiguous.
    # No daemon guessing required.
    print("[0.5/4] Running scrivener pipeline (T1 + System 1)...")
    try:
        subprocess.run(
            [venv_python, os.path.join(AIM_ROOT, "hooks", "session_summarizer.py"), "--light"],
            cwd=AIM_ROOT, check=True, timeout=60
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[WARN] Scrivener pipeline failed (non-fatal): {e}")

    # 1. Trigger Pulse (HANDOFF.md + CURRENT_PULSE.md refresh only)
    # NOTE: REINCARNATION_GAMEPLAN.md is written by the live agent via /reincarnation
    # before this script runs. Do NOT pass intent here — it would trigger a cold LLM
    # overwrite of the gameplan the live agent just wrote.
    print("[1/4] Refreshing handoff pulse (CURRENT_PULSE.md + HANDOFF.md)...")

    try:
        subprocess.run(
            [venv_python, os.path.join(AIM_ROOT, "scripts", "handoff_pulse_claude.py")],
            cwd=AIM_ROOT, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to generate handoff: {e}")
        sys.exit(1)
        
    # 2. Spawn Detached Tmux Session
    print("[2/4] Spawning new host vessel (tmux session)...")
    session_name = f"aim_reincarnation_{int(time.time())}"
    
    try:
        # Start a detached tmux session running the target agent CLI
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-c", AIM_ROOT, agent_cfg["cmd"]],
            check=True
        )
    except FileNotFoundError:
        print("[ERROR] 'tmux' is not installed. The Reincarnation Protocol requires tmux.")
        print("Please install it: sudo apt install tmux")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to spawn tmux session: {e}")
        sys.exit(1)
        
    # 3. Inject Wake-Up Prompt
    print("[3/4] Injecting context prompt into new vessel...")
    # Give the Claude Code CLI a few seconds to boot up inside tmux
    time.sleep(3)

    wake_up_prompt = agent_cfg["wake_up"]
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, wake_up_prompt, "C-m"],
            check=True
        )
        print(f"      [Success] New agent is awake in tmux session: {session_name}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to inject prompt: {e}")
        # We don't exit here, because tmux is running, maybe they can manually do it.
        
    # 4. The Teleport (Self-Termination)
    print("[4/4] Executing Teleport Sequence...")
    
    # Give the filesystem a final moment to sync atomic writes
    time.sleep(2)
    
    if os.environ.get("TMUX"):
        print("      [Teleport] TMUX detected. Switching clients...")
        try:
            # 1. Get the name of the *current* dying session
            result = subprocess.run(["tmux", "display-message", "-p", "#S"], capture_output=True, text=True)
            current_session = result.stdout.strip()
            
            # 2. Force the user's terminal to switch to the new agent
            subprocess.run(["tmux", "switch-client", "-t", session_name], check=True)
            
            # 3. Assassinate the old session to free memory
            if current_session:
                subprocess.run(["tmux", "kill-session", "-t", current_session])
        except Exception as e:
            print(f"[ERROR] Teleport failed: {e}")
            sys.exit(1)
    else:
        # Fallback for non-tmux users
        print(f"\n[!] You are not in tmux. To view the new agent, run:\n    tmux attach-session -t {session_name}")
        parent_pid = os.getppid()
        try:
            os.kill(parent_pid, signal.SIGTERM)
        except Exception as e:
            print(f"[ERROR] Could not self-terminate: {e}")

if __name__ == "__main__":
    main()
