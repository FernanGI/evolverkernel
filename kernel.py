# -*- coding: utf-8 -*-
"""
Surface Evolver Jupyter Kernel (lazy spawn, manual pexpect; sin REPLWrapper).

Motivación
----------
`pexpect.replwrap.REPLWrapper` resultó frágil con Surface Evolver: el patrón de prompt
`Enter command:` a veces coincidía parcialmente (`Enter command`), dejando `: ` colgando
en el búfer y provocando desincronizaciones y relanzamientos repetidos del proceso
Evolver. Para evitarlo, controlamos explícitamente el ciclo
*spawn → expect(datafile) → send → expect(main prompt) → sendline/expect por comando*.

Flujo de arranque
-----------------
1. Spawn del binario (ruta de `EVOLVER_CMD`, o `shutil.which('evolver')`, o `'evolver'`).
2. Espera prompt de datafile (`Enter new datafile name ...:`); tolerante a espacios.
3. Envía el datafile por defecto (variable `EVOLVER_DATAFILE`; por defecto cadena vacía).
4. Espera prompt principal `Enter command:` (tolerante a espacios).
5. Guarda patrón de prompt (`MAIN_PROMPT_PAT` o fallback) y el hijo `pexpect.spawn`.

Ejecución
---------
- Cada celda se divide en líneas no vacías.
- Por cada línea: `sendline` → `expect(self._prompt_pat)` → salida = `before`.
- Si Evolver muere (EOF), se relanza en el siguiente comando.
- Si `KeyboardInterrupt`, se envía intr al hijo y se intenta recuperar el prompt.

Variables de entorno
--------------------
EVOLVER_CMD            Ruta al binario Evolver (default: `which evolver` o `evolver`).
EVOLVER_DATAFILE       Datafile inicial; cadena vacía => continuar sin cargar.
EVOLVER_KERNEL_DEBUG   Si está definida (cualquier valor), vuelca E/S cruda de Evolver en stderr.

"""

from ipykernel.kernelbase import Kernel
import os
import shutil
import signal
import sys
import pexpect
from pexpect import EOF as PexpectEOF, TIMEOUT as PexpectTIMEOUT

# ---------------------------------------------------------------------------
# Patrones de prompt (regex tolerantes)
# ---------------------------------------------------------------------------
FILE_PROMPT_PAT = r'Enter new datafile name\s*\(none to continue, q to quit\):\s*'
MAIN_PROMPT_PAT = r'Enter command:\s*'


class EvolverKernel(Kernel):
    implementation = 'surface_evolver_kernel'
    implementation_version = '0.2'
    language = 'evolver'
    language_version = '2.70'  # informativo
    banner = 'Surface Evolver kernel'

    language_info = {
        'name': 'evolver',
        'mimetype': 'text/plain',
        'file_extension': '.fe',
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Configuración (lazy spawn: Evolver se lanza en la primera ejecución real)
        self._evolver_cmd = os.environ.get('EVOLVER_CMD', shutil.which('evolver') or 'evolver')
        self._default_datafile = os.environ.get('EVOLVER_DATAFILE', '')
        self._debug = bool(os.environ.get('EVOLVER_KERNEL_DEBUG'))
        self.child = None            # pexpect.spawn instance
        self._prompt_pat = MAIN_PROMPT_PAT  # regex del prompt principal

    # ------------------------------------------------------------------
    # Arranque + handshake
    # ------------------------------------------------------------------
    def _spawn_and_handshake(self, timeout=30):
        """Lanza Surface Evolver y realiza handshake.

        Retorna el objeto ``pexpect.spawn`` listo en el prompt principal.
        Lanza excepción ante fallo grave; el caller la captura.
        """
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            child = pexpect.spawn(
                self._evolver_cmd,
                echo=False,
                encoding='utf-8',
                codec_errors='replace',
                timeout=timeout,
            )

            if self._debug:
                # Ver E/S cruda de Evolver en el stderr del servidor Jupyter
                child.logfile = sys.__stderr__

            # 1) Prompt de datafile (tolerante)
            try:
                child.expect(FILE_PROMPT_PAT, timeout=timeout)
            except PexpectTIMEOUT:
                self._emit_stderr("[EvolverKernel] No vi prompt de datafile; continúo.\n")
            # responder datafile (vacío => continuar sin cargar)
            child.sendline(self._default_datafile)

            # 2) Prompt principal
            try:
                child.expect(MAIN_PROMPT_PAT, timeout=timeout)
            except PexpectTIMEOUT:
                # Nudge
                child.sendline('')
                try:
                    child.expect(MAIN_PROMPT_PAT, timeout=5)
                except PexpectTIMEOUT:
                    self._emit_stderr("[EvolverKernel] No vi prompt principal; uso fallback '> '.\n")
                    self._prompt_pat = r'> '
                    self._emit_stdout("[EvolverKernel] Evolver lanzado con prompt fallback.\n")
                    return child
            # Si llegamos aquí, vimos prompt principal
            self._prompt_pat = MAIN_PROMPT_PAT
            self._emit_stdout("[EvolverKernel] Evolver lanzado. Prompt principal listo.\n")
            return child

        finally:
            signal.signal(signal.SIGINT, sig)

    # ------------------------------------------------------------------
    # Estado del hijo Evolver
    # ------------------------------------------------------------------
    def _alive(self):
        return self.child is not None and self.child.isalive()

    # ------------------------------------------------------------------
    # Asegurar proceso Evolver
    # ------------------------------------------------------------------
    def _ensure_evolver(self):
        if self._alive():
            return
        try:
            self.child = self._spawn_and_handshake(timeout=30)
        except Exception as exc:  # noqa: BLE001
            self.child = None
            self._emit_stderr(f"[EvolverKernel] ERROR lanzando Evolver: {exc}\n")

    # ------------------------------------------------------------------
    # Enviar una línea y capturar salida
    # ------------------------------------------------------------------
    def _run_line(self, line, timeout=None):
        """Envía una línea a Evolver y devuelve la salida (texto antes del prompt)."""
        if timeout is None:
            timeout = None  # bloqueo hasta que aparezca prompt
        self.child.sendline(line)
        self.child.expect(self._prompt_pat, timeout=timeout)
        return self.child.before

    # ------------------------------------------------------------------
    # API Jupyter: ejecutar código de una celda
    # ------------------------------------------------------------------
    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        code = code.rstrip('\n')
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

        # Lazy spawn
        self._ensure_evolver()

        if not self._alive():
            msg = "[EvolverKernel] ERROR: no pude lanzar Surface Evolver.\n"
            if not silent:
                self._emit_stderr(msg)
            return {'status': 'error', 'execution_count': self.execution_count,
                    'ename': 'RuntimeError', 'evalue': msg, 'traceback': []}

        outputs = []

        
        for ln in (l for l in code.splitlines() if l.strip()):
            try:
                out = self._run_line(ln, timeout=None)
            except KeyboardInterrupt:
                self.child.sendintr()
                try:
                    self.child.expect(self._prompt_pat, timeout=2)
                except Exception:  # pragma: no cover
                    pass
                out = self.child.before
            except PexpectEOF:
                self._emit_stderr("[EvolverKernel] Evolver murió (EOF); reinicio.\n")
                self.child = None
                self._ensure_evolver()
                out = ""
            except Exception as e:  # noqa: BLE001
                out = f"[EvolverKernel] Excepción ejecutando '{ln}': {e}\n"
            outputs.append(out)

        text = "".join(outputs)
        if not silent and text:
            self._emit_stdout(text)

        return {'status': 'ok', 'execution_count': self.execution_count,
                'payload': [], 'user_expressions': {}}

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------
    def _emit_stdout(self, text):
        self.send_response(self.iopub_socket, 'stream',
                           {'name': 'stdout', 'text': text})

    def _emit_stderr(self, text):
        self.send_response(self.iopub_socket, 'stream',
                           {'name': 'stderr', 'text': text})
