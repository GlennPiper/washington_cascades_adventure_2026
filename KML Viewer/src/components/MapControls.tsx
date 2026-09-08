type LoadMode = 'replace' | 'append'

interface MapControlsProps {
  loadMode: LoadMode
  onLoadModeChange: (m: LoadMode) => void
  baseMap: string
  onBaseMapChange: (id: string) => void
  showPoints: boolean
  onShowPointsChange: (v: boolean) => void
  showTracks: boolean
  onShowTracksChange: (v: boolean) => void
  showPolygons: boolean
  onShowPolygonsChange: (v: boolean) => void
  selectedSyms: string[]
  onSymFilterChange: (sym: string, checked: boolean) => void
  uniqueSymValues: string[]
  hasPoints: boolean
  hasTracks: boolean
  hasPolygons: boolean
  keepScreenAwake: boolean
  onKeepScreenAwakeChange: (v: boolean) => void
}

const BASE_MAPS: { id: string; label: string }[] = [
  { id: 'osm', label: 'OpenStreetMap' },
  { id: 'topo', label: 'USGS Topo' },
  { id: 'satellite', label: 'Satellite' },
]

export function MapControls({
  loadMode,
  onLoadModeChange,
  baseMap,
  onBaseMapChange,
  showPoints,
  onShowPointsChange,
  showTracks,
  onShowTracksChange,
  showPolygons,
  onShowPolygonsChange,
  selectedSyms,
  onSymFilterChange,
  uniqueSymValues,
  hasPoints,
  hasTracks,
  hasPolygons,
  keepScreenAwake,
  onKeepScreenAwakeChange,
}: MapControlsProps) {
  return (
    <div className="map-controls">
      <div className="control-group load-mode">
        <span>On load:</span>
        <label>
          <input
            type="radio"
            name="loadMode"
            checked={loadMode === 'replace'}
            onChange={() => onLoadModeChange('replace')}
          />
          Replace
        </label>
        <label>
          <input
            type="radio"
            name="loadMode"
            checked={loadMode === 'append'}
            onChange={() => onLoadModeChange('append')}
          />
          Append
        </label>
      </div>
      <div className="control-group">
        <label>Base map:</label>
        <select value={baseMap} onChange={(e) => onBaseMapChange(e.target.value)}>
          {BASE_MAPS.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </div>
      <div className="control-group layers">
        <span>Layers:</span>
        {hasPoints && (
          <label>
            <input
              type="checkbox"
              checked={showPoints}
              onChange={(e) => onShowPointsChange(e.target.checked)}
            />
            Points
          </label>
        )}
        {hasPoints && uniqueSymValues.length > 0 && (
          <div className="control-group waypoint-filter">
            <span>Type:</span>
            {uniqueSymValues.map((sym) => (
              <label key={sym} className="waypoint-type-option">
                <input
                  type="checkbox"
                  checked={selectedSyms.includes(sym)}
                  onChange={(e) => onSymFilterChange(sym, e.target.checked)}
                />
                {sym}
              </label>
            ))}
          </div>
        )}
        {hasTracks && (
          <label>
            <input
              type="checkbox"
              checked={showTracks}
              onChange={(e) => onShowTracksChange(e.target.checked)}
            />
            Tracks
          </label>
        )}
        {hasPolygons && (
          <label>
            <input
              type="checkbox"
              checked={showPolygons}
              onChange={(e) => onShowPolygonsChange(e.target.checked)}
            />
            Polygons
          </label>
        )}
      </div>
      <div className="control-group">
        <label>
          <input
            type="checkbox"
            checked={keepScreenAwake}
            onChange={(e) => onKeepScreenAwakeChange(e.target.checked)}
          />
          Keep screen on
        </label>
      </div>
    </div>
  )
}
