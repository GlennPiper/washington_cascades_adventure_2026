import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { FileLoader } from './components/FileLoader'
import { KmlMap } from './components/KmlMap'
import { MapControls } from './components/MapControls'
import { StatusBar } from './components/StatusBar'
import { processGeoFile, mergeKmlResults, getUniqueSymValues } from './lib/kmlParser'
import type { KmlLoadResult } from './types'
import './App.css'

type LoadMode = 'replace' | 'append'

function App() {
  const [results, setResults] = useState<KmlLoadResult[]>([])
  const [loadMode, setLoadMode] = useState<LoadMode>('replace')
  const [error, setError] = useState<string | null>(null)
  const [baseMap, setBaseMap] = useState('topo')
  const [showPoints, setShowPoints] = useState(true)
  const [showTracks, setShowTracks] = useState(true)
  const [showPolygons, setShowPolygons] = useState(true)
  const [keepScreenAwake, setKeepScreenAwake] = useState(true)
  const wakeLockRef = useRef<WakeLockSentinel | null>(null)

  useEffect(() => {
    if (!('wakeLock' in navigator)) return

    const acquireWakeLock = async () => {
      try {
        wakeLockRef.current = await navigator.wakeLock.request('screen')
      } catch {
        // Device may deny the request (e.g. low battery); ignore silently
      }
    }

    const releaseWakeLock = async () => {
      if (wakeLockRef.current) {
        await wakeLockRef.current.release()
        wakeLockRef.current = null
      }
    }

    if (keepScreenAwake) {
      acquireWakeLock()

      // Re-acquire after the page becomes visible again (wake lock is
      // automatically released when the page is hidden)
      const onVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
          acquireWakeLock()
        }
      }
      document.addEventListener('visibilitychange', onVisibilityChange)
      return () => {
        document.removeEventListener('visibilitychange', onVisibilityChange)
        releaseWakeLock()
      }
    } else {
      releaseWakeLock()
    }
  }, [keepScreenAwake])

  const mergedResult = useMemo(() => mergeKmlResults(results), [results])
  const [selectedSyms, setSelectedSyms] = useState<string[]>([])
  const uniqueSymValues = useMemo(
    () => (mergedResult.geojson.features.length > 0 ? getUniqueSymValues(mergedResult.geojson) : []),
    [mergedResult.geojson]
  )
  useEffect(() => {
    setSelectedSyms([])
  }, [results])
  const handleSymFilterChange = useCallback((sym: string, checked: boolean) => {
    setSelectedSyms((prev) =>
      checked ? [...prev, sym] : prev.filter((s) => s !== sym)
    )
  }, [])

  const handleLoad = useCallback((xml: string, fileName: string) => {
    try {
      setError(null)
      const parsed = processGeoFile(xml, fileName)
      setResults((prev) =>
        loadMode === 'replace' ? [parsed] : [...prev, parsed]
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to parse file')
    }
  }, [loadMode])

  const handleError = useCallback((msg: string) => {
    setError(msg)
  }, [])

  return (
    <div className="app">
      <header className="toolbar">
        <FileLoader onLoad={handleLoad} onError={handleError} />
        <MapControls
          loadMode={loadMode}
          onLoadModeChange={setLoadMode}
          baseMap={baseMap}
          onBaseMapChange={setBaseMap}
          showPoints={showPoints}
          onShowPointsChange={setShowPoints}
          showTracks={showTracks}
          onShowTracksChange={setShowTracks}
          showPolygons={showPolygons}
          onShowPolygonsChange={setShowPolygons}
          selectedSyms={selectedSyms}
          onSymFilterChange={handleSymFilterChange}
          uniqueSymValues={uniqueSymValues}
          hasPoints={(mergedResult?.pointCount ?? 0) > 0}
          hasTracks={(mergedResult?.trackCount ?? 0) > 0}
          hasPolygons={(mergedResult?.polygonCount ?? 0) > 0}
          keepScreenAwake={keepScreenAwake}
          onKeepScreenAwakeChange={setKeepScreenAwake}
        />
      </header>
      <main className="map-area">
        <KmlMap
          geojson={mergedResult.geojson.features.length > 0 ? mergedResult.geojson : null}
          geojsonKey={results.map((r) => r.fileName).join('|')}
          baseMap={baseMap}
          showPoints={showPoints}
          showTracks={showTracks}
          showPolygons={showPolygons}
          selectedSyms={selectedSyms}
        />
      </main>
      <footer className="footer">
        {error && <div className="error">{error}</div>}
        <StatusBar result={results.length > 0 ? mergedResult : null} />
      </footer>
    </div>
  )
}

export default App
