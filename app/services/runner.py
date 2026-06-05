"""Wrapper sobre subprocess que registra todo en el log de la operación."""
import subprocess
from typing import Iterable, List, Optional


def run(cmd: List[str], input_text: Optional[str] = None, timeout: int = 600,
        cwd: Optional[str] = None, env: Optional[dict] = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_sudo(cmd: List[str], **kw) -> tuple[int, str, str]:
    return run(["sudo", "-n"] + cmd, **kw)


def shell_log(parts: Iterable, log_buf: list) -> str:
    """Append una línea al buffer y retornar la línea formateada."""
    line = " ".join(str(p) for p in parts)
    log_buf.append(line)
    return line
