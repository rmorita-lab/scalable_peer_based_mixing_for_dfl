import React, { useState } from 'react';
import { useNodeStatus } from './hooks/useNodeStatus';
import { useMetricsStream } from './hooks/useMetricsStream';
import { useMetricsIndex } from './hooks/useMetricsIndex';
import { useNodeControls } from './hooks/useNodeControls';
import { useExperimentConfig } from './hooks/useExperimentConfig';
import { useScenarioIndicators } from './hooks/useScenarioIndicators';
import { ConfigPanel } from './components/ConfigPanel/ConfigPanel';
import { ScenarioIndicators } from './components/ScenarioIndicators/ScenarioIndicators';
import { NodeStatusTable } from './components/NodeStatusTable/NodeStatusTable';
import { MetricsSidebar } from './components/MetricsSidebar/MetricsSidebar';
import { ChartsGrid } from './components/ChartsGrid/ChartsGrid';
import { createColorMap } from './utils/colors';
import styles from './Dashboard.module.css';

export default function Dashboard() {
  const [currentPath, setCurrentPath] = useState(() =>
    typeof window !== 'undefined' ? window.location.pathname : '/'
  );

  const isMoqMode = currentPath.startsWith('/moq');

  // Listen to popstate (back/forward browser buttons)
  React.useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigateTo = (path) => {
    if (typeof window !== 'undefined') {
      window.history.pushState({}, '', path);
      setCurrentPath(path);
    }
  };

  const initialOverrides = React.useMemo(() => {
    return isMoqMode ? { moq_enabled: true } : { moq_enabled: false };
  }, [isMoqMode]);

  const [selectedMetrics, setSelectedMetrics] = useState([]);
  const { nodes, isRunning } = useNodeStatus();
  const { metrics, clearMetrics } = useMetricsStream();
  const {
    config,
    errors: configErrors,
    isValid: isConfigValid,
    updateConfig,
    getConfigForSubmit,
  } = useExperimentConfig(initialOverrides);

  // Sync moq_enabled if path changes
  React.useEffect(() => {
    updateConfig('moq_enabled', isMoqMode);
  }, [isMoqMode, updateConfig]);

  const { indicators, isLoading: indicatorsLoading } = useScenarioIndicators(config);
  const {
    nodeNames: indexedNodeNames,
    metricInfo,
    currentRounds,
    chartIndex,
  } = useMetricsIndex(metrics);

  function handleReset() {
    clearMetrics();
    setSelectedMetrics([]);
  }

  const {
    handleStart: startNodes,
    handleStop,
    isStarting,
    isStopping,
    error: controlsError,
    clearError,
  } = useNodeControls({
    onStart: handleReset,
    onStop: handleReset,
  });

  function handleStart() {
    if (isConfigValid) startNodes(getConfigForSubmit());
  }

  function toggleMetric(field) {
    setSelectedMetrics((prev) =>
      prev.includes(field) ? prev.filter((m) => m !== field) : [...prev, field]
    );
  }

  const nodeNameSet = new Set(indexedNodeNames);
  nodes.forEach((node) => {
    if (node.name) nodeNameSet.add(node.name);
  });
  const nodeNames = [...nodeNameSet].sort();
  const nodeColors = createColorMap(nodeNames);

  const metricsByGroup = {};
  Object.entries(metricInfo).forEach(([field, info]) => {
    if (!metricsByGroup[info.group]) metricsByGroup[info.group] = [];
    metricsByGroup[info.group].push({ field, ...info });
  });

  const chartData = {};
  selectedMetrics.forEach((field) => {
    chartData[field] = chartIndex[field] || [];
  });

  const disabled = isRunning || isStarting;

  return (
    <div className={styles.container}>
      {/* Protocol Mode Navigation Tabs */}
      <nav className={styles.navBar}>
        <div className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tab} ${!isMoqMode ? styles.activeTab : ''}`}
            onClick={() => navigateTo('/')}
          >
            Standard QUIC
          </button>
          <button
            type="button"
            className={`${styles.tab} ${isMoqMode ? styles.activeTab : ''}`}
            onClick={() => navigateTo('/moq')}
          >
            Media over QUIC (MoQ)
          </button>
        </div>
        <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
          URL: <code>{isMoqMode ? '/moq' : '/'}</code>
        </div>
      </nav>

      {controlsError && (
        <div className={styles.banner} onClick={clearError}>
          {controlsError}
        </div>
      )}

      <header className={styles.header}>
        <div className={styles.titleArea}>
          <h1 className={styles.title}>MixDfl</h1>
          {isMoqMode ? (
            <span className={`${styles.badge} ${styles.badgeMoq}`}>Media over QUIC (MoQ)</span>
          ) : (
            <span className={`${styles.badge} ${styles.badgeStandard}`}>Standard QUIC</span>
          )}
        </div>
        <div className={styles.controls}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleStart}
            disabled={isRunning || isStopping || !isConfigValid}
          >
            {isStarting ? 'Starting...' : 'Start'}
          </button>
          <button
            className={`${styles.btn} ${styles.btnDanger}`}
            onClick={handleStop}
            disabled={(!isRunning && !isStopping) || isStarting}
          >
            {isStopping ? 'Stopping...' : 'Stop'}
          </button>
        </div>
      </header>

      {/* MoQ Protocol Details Banner (Only in /moq mode) */}
      {isMoqMode && (
        <div className={styles.moqInfoCard}>
          <div className={styles.moqInfoTitle}>
            <span>⚡ MoQ Hierarchical Namespace Framing Active</span>
          </div>
          <div>
            Packets are framed with MoQ headers following <code>moq-dev/moq</code> specifications,
            enabling prefix-based routing, cache inspection, and group sequencing:
          </div>
          <div className={styles.moqInfoGrid}>
            <div className={styles.moqInfoItem}>
              <span className={styles.moqInfoKey}>Track Namespace: </span>
              <span className={styles.moqInfoVal}>dfl/node_&#123;id&#125;/model_part</span>
            </div>
            <div className={styles.moqInfoItem}>
              <span className={styles.moqInfoKey}>Track Name: </span>
              <span className={styles.moqInfoVal}>weights</span>
            </div>
            <div className={styles.moqInfoItem}>
              <span className={styles.moqInfoKey}>Group ID: </span>
              <span className={styles.moqInfoVal}>round (varint)</span>
            </div>
            <div className={styles.moqInfoItem}>
              <span className={styles.moqInfoKey}>Object ID: </span>
              <span className={styles.moqInfoVal}>chunk_idx (varint)</span>
            </div>
          </div>
        </div>
      )}

      <ConfigPanel
        config={config}
        errors={configErrors}
        onUpdate={updateConfig}
        disabled={disabled}
        isRunning={isRunning}
        adjacency={indicators?.topology?.adjacency}
      />
      <ScenarioIndicators indicators={indicators} isLoading={indicatorsLoading} />
      <NodeStatusTable nodes={nodes} nodeColors={nodeColors} currentRounds={currentRounds} />

      <div className={styles.metricsLayout}>
        <MetricsSidebar
          metricsByGroup={metricsByGroup}
          selectedMetrics={selectedMetrics}
          onToggle={toggleMetric}
        />
        <ChartsGrid
          selectedMetrics={selectedMetrics}
          metricInfo={metricInfo}
          chartData={chartData}
          nodeNames={nodeNames}
          nodeColors={nodeColors}
        />
      </div>
    </div>
  );
}
