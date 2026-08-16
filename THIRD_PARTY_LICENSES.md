# Third-Party Licenses

Local-Jarvis uses third-party software, models, datasets, and services.
Each component remains subject to its own license and terms.

## Runtime and AI

### Ollama
- Purpose: Local LLM runtime
- Website: https://ollama.com/
- License: See Ollama's current license and terms
- Local-Jarvis does not distribute Ollama.

### Qwen3
- Purpose: Default local language model
- Model: `qwen3:4b`
- License: See the specific Qwen model license
- Local-Jarvis does not claim ownership of the Qwen model or its weights.

### Moondream
- Purpose: Local image/vision understanding
- License: See the specific Moondream model license
- Model files are not distributed with Local-Jarvis unless explicitly stated.

### Whisper
- Purpose: Local speech recognition
- License: MIT
- Repository: https://github.com/openai/whisper

## Voice

### Piper
- Purpose: Local text-to-speech
- License: See the Piper project and the specific voice model license
- Voice models may have licenses separate from the Piper software.
- Local-Jarvis does not claim ownership of third-party voice models.

## Location Data

### MaxMind GeoLite2
- Purpose: Offline IP-based geographic lookup fallback
- License/Terms: MaxMind GeoLite2 terms
- The GeoLite2 database is not bundled with Local-Jarvis.
- Users must obtain the database according to MaxMind's terms.

### OpenStreetMap -- Overpass API
- Purpose: Nearby point-of-interest search (`find_nearby_place`)
- Website: https://overpass-api.de/ , data from https://www.openstreetmap.org/
- License: Map data is licensed under the Open Database License (ODbL) --
  see https://www.openstreetmap.org/copyright
- Local-Jarvis queries the public Overpass API instance directly at
  request time; no OpenStreetMap data is bundled or redistributed.
- The public Overpass instance is a shared community resource, not
  intended for high-volume or production use. Excessive automated use
  may be rate-limited or blocked.

### OpenStreetMap -- Nominatim
- Purpose: Geocoding a destination name into coordinates (`get_route`)
- Website: https://nominatim.org/
- License: Same ODbL-licensed OpenStreetMap data as above; see
  https://www.openstreetmap.org/copyright
- Usage policy: https://operations.osmfoundation.org/policies/nominatim/
  requires a descriptive User-Agent identifying the requesting
  application (already set in `tools/routing.py`) and prohibits
  heavy/bulk usage of the public instance.

### OpenRouteService
- Purpose: Walking/cycling/driving route directions (`get_route`)
- Website: https://openrouteservice.org/
- License/Terms: See OpenRouteService's terms of service
- Requires a free API key (`ors_api_key` in `jarvis_config.json`),
  obtained directly by the user. Local-Jarvis does not bundle or embed
  any API key. Usage is subject to whatever quota/rate limits apply to
  the user's own key.

### OSRM (Open Source Routing Machine) -- public demo server
- Purpose: Keyless driving-direction fallback when no OpenRouteService
  API key is configured (`get_route`)
- Website: http://project-osrm.org/ , demo server at
  https://router.project-osrm.org/
- License: OSRM itself is BSD-licensed; the *public demo server* is
  explicitly documented by its maintainers as a demonstration service
  not intended for production or heavy use, with no uptime or rate
  guarantees. Local-Jarvis uses it only as a no-setup fallback -- for
  reliable use, self-hosting OSRM or configuring an OpenRouteService key
  is recommended.

## Web Services (no API key, no data returned to Jarvis)

### Google Maps
- Purpose: `open_google_maps` / `navigate_google_maps` / `search_google_maps`
  open a Google Maps URL in the user's default browser
- Website: https://maps.google.com/
- License/Terms: Subject to Google's Terms of Service
  (https://www.google.com/intl/en/help/terms_maps/)
- Local-Jarvis does not call the Google Maps API and does not use an
  API key -- these tools only construct a URL and hand it to the
  system's default browser via `webbrowser.open()`. No location or
  routing data is returned to or processed by Jarvis itself.

## Python Dependencies

Local-Jarvis also depends on third-party Python packages listed in:

`requirements.txt`

Notable additions relevant to location/routing/calendar features:
- `icalendar` -- reads/writes the local `.ics` calendar file (BSD-2-Clause)
- `geoip2` -- reads the local MaxMind GeoLite2 database (Apache-2.0)

Each dependency remains subject to its respective license.

Users redistributing Local-Jarvis should review the licenses of all installed
dependencies and optional components.

## Important Notice

The MIT License applies to the Local-Jarvis source code authored by the
Local-Jarvis contributors. It does not replace or override the licenses of
third-party software, models, datasets, voices, or other external components.

Third-party components may have additional attribution, redistribution,
commercial-use, or usage requirements. Users are responsible for complying
with the applicable terms for those components.
