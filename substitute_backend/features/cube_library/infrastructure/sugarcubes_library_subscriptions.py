#    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Own deferred subscriptions to SugarCubes library-change events."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast


@dataclass
class _LibraryChangeSubscription:
    """Track one listener until SugarCubes services become available."""

    listener: Callable[[Mapping[str, object]], None]
    unsubscribe: Callable[[], None] | None = None


class SugarCubesLibrarySubscriptions:
    """Coordinate deferred listener attachment independently from route calls."""

    def __init__(self) -> None:
        """Initialize an empty thread-safe subscription registry."""

        self._lock = threading.Lock()
        self._subscriptions: list[_LibraryChangeSubscription] = []

    def subscribe(
        self,
        listener: Callable[[Mapping[str, object]], None],
        *,
        loaded_services: object | None,
    ) -> Callable[[], None]:
        """Record one listener and attach it immediately when services are loaded."""

        subscription = _LibraryChangeSubscription(listener=listener)
        with self._lock:
            self._subscriptions.append(subscription)
        if loaded_services is not None:
            self._activate(subscription, loaded_services)
        return lambda: self._unsubscribe(subscription)

    def activate_pending(self, services: object) -> None:
        """Attach all listeners deferred until the SugarCubes graph was available."""

        with self._lock:
            subscriptions = [
                subscription
                for subscription in self._subscriptions
                if subscription.unsubscribe is None
            ]
        for subscription in subscriptions:
            self._activate(subscription, services)

    def _activate(
        self,
        subscription: _LibraryChangeSubscription,
        services: object,
    ) -> None:
        """Attach one listener if the active library supports change events."""

        with self._lock:
            if subscription.unsubscribe is not None:
                return
            if subscription not in self._subscriptions:
                return
        library = getattr(services, "library", None)
        subscribe = getattr(library, "subscribe_library_changed", None)
        if not callable(subscribe):
            return
        unsubscribe = subscribe(subscription.listener)
        if not callable(unsubscribe):
            return
        unsubscribe_callback = cast("Callable[[], None]", unsubscribe)
        with self._lock:
            if subscription not in self._subscriptions:
                unsubscribe_callback()
                return
            if subscription.unsubscribe is not None:
                unsubscribe_callback()
                return
            subscription.unsubscribe = unsubscribe_callback

    def _unsubscribe(self, subscription: _LibraryChangeSubscription) -> None:
        """Remove one pending or active listener and release its SugarCubes hook."""

        with self._lock:
            self._subscriptions = [
                active for active in self._subscriptions if active is not subscription
            ]
            unsubscribe = subscription.unsubscribe
            subscription.unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()
