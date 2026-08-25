from just_playback import Playback


class AudioManager:
    """
    A multi-track Audio Manager powered by miniaudio (via just_playback).
    """

    def __init__(self):
        self._tracks: dict[str, Playback] = {}
        self._track_volumes: dict[str, float] = {}
        self._global_volume: float = 1.0

    def load(self, track_id: str, filepath: str) -> None:
        """Loads an audio file and assigns it a string ID."""
        player = Playback()
        player.load_file(filepath)

        self._tracks[track_id] = player
        self._track_volumes[track_id] = 1.0
        player.set_volume(self._global_volume)

    # --- PLAYBACK CONTROLS ---

    def play(self, track_id: str, loop: bool = False) -> None:
        """Plays the track from the beginning."""
        if track := self._get_track(track_id):
            track.loop_at_end(loop)
            track.play()

    def pause(self, track_id: str) -> None:
        """Pauses a currently playing track."""
        if track := self._get_track(track_id):
            track.pause()

    def resume(self, track_id: str) -> None:
        """Resumes a paused track from where it stopped."""
        if track := self._get_track(track_id):
            track.resume()

    def stop(self, track_id: str) -> None:
        """Stops the track completely and resets position to 0."""
        if track := self._get_track(track_id):
            track.stop()

    def stop_all(self) -> None:
        """Stops all loaded tracks simultaneously."""
        for track in self._tracks.values():
            track.stop()

    # --- TIME POSITION CONTROL ---

    def seek(self, track_id: str, position_seconds: float) -> None:
        """Jumps to a specific time in the track."""
        if track := self._get_track(track_id):
            # Clamp the seek time between 0 and the track's total duration
            safe_position = max(0.0, min(position_seconds, track.duration))
            track.seek(safe_position)

    def get_position(self, track_id: str) -> float:
        """Returns the current playback position in seconds."""
        if track := self._get_track(track_id):
            return track.curr_pos
        return 0.0

    def get_duration(self, track_id: str) -> float:
        """Returns the total duration of the track in seconds."""
        if track := self._get_track(track_id):
            return track.duration
        return 0.0

    # --- VOLUME CONTROL ---

    def set_volume(self, track_id: str, volume: float) -> None:
        """Sets individual track volume (0.0 to 1.0+)."""
        if track := self._get_track(track_id):
            safe_volume = max(0.0, volume)
            self._track_volumes[track_id] = safe_volume
            # Apply individual volume scaled by the global master volume
            track.set_volume(safe_volume * self._global_volume)

    def set_global_volume(self, volume: float) -> None:
        """Scales the volume of all tracks simultaneously (Master Volume)."""
        self._global_volume = max(0.0, volume)
        for t_id, track in self._tracks.items():
            indiv_vol = self._track_volumes.get(t_id, 1.0)
            track.set_volume(indiv_vol * self._global_volume)

    # --- STATES ---

    def set_loop(self, track_id: str, loop: bool) -> None:
        """Toggles looping for a specific track on the fly."""
        if track := self._get_track(track_id):
            track.loop_at_end(loop)

    def is_playing(self, track_id: str) -> bool:
        """Returns True if the track is actively outputting audio."""
        if track := self._get_track(track_id):
            return track.playing
        return False

    def is_paused(self, track_id: str) -> bool:
        """Returns True if the track is paused."""
        if track := self._get_track(track_id):
            return track.paused
        return False

    def is_active(self, track_id: str) -> bool:
        """Returns True if the track is playing OR paused (but not stopped)."""
        if track := self._get_track(track_id):
            return track.active
        return False

    # --- PRIVATE HELPERS ---

    def _get_track(self, track_id: str) -> Playback | None:
        """Safely fetches a track by ID."""
        if track_id not in self._tracks:
            print(f"Warning: Track '{track_id}' not found.")
            return None
        return self._tracks[track_id]
