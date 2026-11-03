"""Darwin process identity: libproc creation token, ESRCH=dead vs EPERM=unknown."""
import ctypes
import errno
import sys
from types import SimpleNamespace

import pytest

import database_process_identity as process_identity

PID = 4242
TBSDINFO_SIZE = 136
START_TVSEC = 120
START_TVUSEC = 128


class FakeLibproc:
    """Model libproc, including calls that leave errno untouched."""

    def __init__(self, *, tvsec=None, tvusec=0, written=TBSDINFO_SIZE, error=None):
        self.tvsec = tvsec
        self.tvusec = tvusec
        self.written = written
        self.error = error
        self.calls = []
        self.entry_errno = []

    def proc_pidinfo(self, pid, flavor, arg, buffer, size):
        self.calls.append((pid, flavor, arg, size))
        self.entry_errno.append(ctypes.get_errno())
        if self.error is not None:
            ctypes.set_errno(self.error)
            return self.written
        if self.tvsec is not None:
            payload = ctypes.create_string_buffer(TBSDINFO_SIZE)
            payload[START_TVSEC:START_TVSEC + 8] = self.tvsec.to_bytes(8, "little")
            payload[START_TVUSEC:START_TVUSEC + 8] = self.tvusec.to_bytes(8, "little")
            ctypes.memmove(buffer, payload, TBSDINFO_SIZE)
        return self.written


@pytest.fixture
def darwin(monkeypatch):
    """Route the macOS path through a fake on any host."""
    monkeypatch.setattr(sys, "platform", "darwin")

    def install(**kwargs):
        fake = FakeLibproc(**kwargs)
        monkeypatch.setattr(process_identity, "_darwin_libproc", lambda: fake)
        return fake

    return install


def test_proc_bsdinfo_layout_matches_kernel_header():
    assert process_identity._PROC_PIDTBSDINFO == 3
    assert (
        process_identity._BSDINFO_SIZE,
        process_identity._BSDINFO_START_TVSEC,
        process_identity._BSDINFO_START_TVUSEC,
    ) == (136, 120, 128)


def test_darwin_token_zero_pads_microseconds():
    raw = bytearray(process_identity._BSDINFO_SIZE)
    raw[START_TVSEC:START_TVSEC + 8] = (1_700_000_000).to_bytes(8, "little")
    raw[START_TVUSEC:START_TVUSEC + 8] = (7).to_bytes(8, "little")

    assert process_identity._darwin_start_token(bytes(raw)) == "1700000000.000007"


def test_darwin_reads_creation_token_from_proc_bsdinfo(darwin):
    fake = darwin(tvsec=1_700_000_000, tvusec=123456)

    state, token = process_identity.inspect_process(PID)

    assert (state, token) == ("alive", "1700000000.123456")
    assert fake.calls == [(PID, 3, 0, TBSDINFO_SIZE)]


def test_darwin_is_not_the_generic_unknown_fallback(darwin):
    darwin(tvsec=1_700_000_000)

    assert process_identity.inspect_process(PID)[0] == "alive"


def test_darwin_esrch_is_dead(darwin):
    darwin(written=0, error=errno.ESRCH)

    assert process_identity.inspect_process(PID) == ("dead", None)


def test_darwin_eperm_is_unknown_not_dead(darwin):
    darwin(written=0, error=errno.EPERM)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_other_errno_is_unknown(darwin):
    darwin(written=0, error=errno.EINVAL)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_short_read_is_unknown(darwin):
    darwin(written=8)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_short_read_with_stale_esrch_is_still_unknown(darwin):
    darwin(written=8)
    ctypes.set_errno(errno.ESRCH)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_clears_stale_errno_before_probing(darwin):
    fake = darwin(tvsec=1_700_000_000)
    ctypes.set_errno(errno.ESRCH)

    process_identity.inspect_process(PID)

    assert fake.entry_errno == [0]


def test_darwin_native_failure_with_clean_errno_is_unknown(darwin):
    darwin(written=0, error=0)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_libproc_load_failure_is_unknown(darwin, monkeypatch):
    def unavailable():
        raise OSError("libproc not available")

    monkeypatch.setattr(process_identity, "_darwin_libproc", unavailable)

    assert process_identity.inspect_process(PID) == ("unknown", None)


def test_darwin_never_probes_the_pid(darwin):
    fake = darwin()
    process_identity.inspect_process(0)

    assert fake.calls == []


def test_darwin_liveness_alive_when_token_matches(darwin):
    darwin(tvsec=1_700_000_000, tvusec=7)
    owner = _owner(process_identity.inspect_process(PID)[1])

    assert process_identity.owner_liveness(owner) == "alive"


def test_darwin_reused_pid_is_dead_owner(darwin):
    darwin(tvsec=1_700_000_000, tvusec=7)
    stale_owner = _owner("1699999999.000001")

    assert process_identity.owner_liveness(stale_owner) == "dead"


def test_darwin_unknown_liveness_never_authorises_death(darwin):
    darwin(written=0, error=errno.EPERM)
    owner = _owner("1700000000.123456")

    assert process_identity.owner_liveness(owner) == "unknown"


def test_darwin_token_without_stored_token_is_unknown(darwin):
    darwin(tvsec=1_700_000_000)
    owner = _owner(None)

    assert process_identity.owner_liveness(owner) == "unknown"


def _owner(process_started):
    return SimpleNamespace(
        released_at=None,
        host_id=process_identity.local_host_id(),
        process_id=PID,
        process_started=process_started,
    )
