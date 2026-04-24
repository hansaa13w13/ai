"""brain_lock — yarış koşulu / reentrant davranış."""
from __future__ import annotations
import threading
import time

from predator import brain


class TestBrainLockReentrant:
    def test_reentrant_same_thread(self):
        # Aynı thread içiçe acquire edebilmeli (RLock).
        with brain.brain_lock():
            with brain.brain_lock():
                assert True

    def test_serializes_other_threads(self):
        """İki thread aynı kilidi alıp brain dict'ini RMW yaparsa ezilme olmamalı."""
        shared = {"counter": 0}
        ITER = 200

        def worker():
            for _ in range(ITER):
                with brain.brain_lock():
                    cur = shared["counter"]
                    # Küçük bir gecikme: kilit yoksa yarış mutlaka kaybeder.
                    time.sleep(0)
                    shared["counter"] = cur + 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert shared["counter"] == 4 * ITER

    def test_lock_released_after_exception(self):
        """with-bloğunda exception atılsa dahi kilit serbest kalmalı."""
        try:
            with brain.brain_lock():
                raise RuntimeError("bilerek hata")
        except RuntimeError:
            pass
        # Eğer kilit bırakılmasaydı bu acquire ebediyen takılırdı.
        with brain.brain_lock():
            assert True
