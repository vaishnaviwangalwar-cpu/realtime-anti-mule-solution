import React, { useEffect, useState } from 'react';
import { Container, Typography, Grid, Paper, List, ListItem, ListItemText, Divider, Box } from '@mui/material';
import { io } from 'socket.io-client';
import Heatmap from './components/Heatmap';
import NetworkGraph from './components/NetworkGraph';
import AlertList from './components/AlertList';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

function App() {
  const [alerts, setAlerts] = useState([]);
  const [heatmapData, setHeatmapData] = useState([]);
  const [graphData, setGraphData] = useState(null);

  // WebSocket connection for real‑time alerts & heatmap updates
  useEffect(() => {
    const socket = io(WS_URL, { transports: ['websocket'] });
    socket.on('connect', () => console.log('WS connected'));
    socket.on('alert', (msg) => setAlerts((prev) => [msg, ...prev].slice(0, 50));
    socket.on('heatmap', (msg) => setHeatmapData(msg));
    socket.on('graph', (msg) => setGraphData(msg));
    return () => socket.disconnect();
  }, []);

  // Initial fetch for static data (alerts, heatmap, graph) – fallback if WS not ready
  useEffect(() => {
    async function fetchInitial() {
      try {
        const [aRes, hRes, gRes] = await Promise.all([
          fetch(`${API_URL}/api/v1/alerts?page=1&size=20`).then(r => r.json()),
          fetch(`${API_URL}/api/v1/heatmap`).then(r => r.json()),
          fetch(`${API_URL}/api/v1/graph/clusters`).then(r => r.json())
        ]);
        setAlerts(aRes.alerts || []);
        setHeatmapData(hRes || []);
        setGraphData(gRes || null);
      } catch (e) {
        console.error('Failed to fetch initial data', e);
      }
    }
    fetchInitial();
  }, []);

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      <Typography variant="h4" gutterBottom>
        Fraud Intelligence Dashboard
      </Typography>
      <Grid container spacing={3}>
        {/* Alerts Panel */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: '100%', overflow: 'auto' }} elevation={3}>
            <Typography variant="h6" gutterBottom>
              Recent Alerts
            </Typography>
            <AlertList alerts={alerts} />
          </Paper>
        </Grid>
        {/* Heatmap */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2, height: 400 }} elevation={3}>
            <Typography variant="h6" gutterBottom>
              Portfolio Risk Heatmap
            </Typography>
            <Heatmap data={heatmapData} />
          </Paper>
        </Grid>
        {/* Network Graph */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2, height: 600 }} elevation={3}>
            <Typography variant="h6" gutterBottom>
              Mule Network Graph
            </Typography>
            {graphData ? <NetworkGraph data={graphData} /> : <Box>Loading graph…</Box>}
          </Paper>
        </Grid>
      </Grid>
    </Container>
  );
}

export default App;
