import React, { useEffect, useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogContentText, CircularProgress, Divider, Typography } from '@mui/material';

/**
 * AlertDetail shows a modal with rich information for a selected alert.
 * Props:
 *   - open: boolean – whether the dialog is visible
 *   - onClose: () => void – callback when dialog is dismissed
 *   - alert: alert object (must contain account_id, type, timestamp, drift_score)
 */
export default function AlertDetail({ open, onClose, alert }) {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(false);

  // Pull extra data from the API when an alert is selected.
  useEffect(() => {
    if (!open || !alert) return;
    setLoading(true);
    const fetchDetails = async () => {
      try {
        const res = await fetch(`${process.env.REACT_APP_API_URL}/api/v1/accounts/${alert.account_id}/behavioral-dna`);
        const json = await res.json();
        setDetails(json);
      } catch (e) {
        console.error('Failed to fetch alert details', e);
      } finally {
        setLoading(false);
      }
    };
    fetchDetails();
  }, [open, alert]);

  if (!alert) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Alert Details – {alert.account_id}</DialogTitle>
      <DialogContent dividers>
        <DialogContentText>
          <strong>Type:</strong> {alert.type}<br />
          <strong>Timestamp:</strong> {new Date(alert.timestamp).toLocaleString()}<br />
          <strong>Drift Score:</strong> {alert.drift_score?.toFixed(3)}
        </DialogContentText>
        <Divider sx={{ my: 2 }} />
        {loading ? (
          <CircularProgress />
        ) : details ? (
          <React.Fragment>
            <Typography variant="subtitle1" gutterBottom>Behavioral DNA Embedding</Typography>
            <pre style={{ overflowX: 'auto', background: '#f5f5f5', padding: '8px' }}>
{JSON.stringify(details.embedding, null, 2)}
            </pre>
            <Typography variant="subtitle1" gutterBottom>Recent Transactions (sample)</Typography>
            <pre style={{ overflowX: 'auto', background: '#f5f5f5', padding: '8px' }}>
{JSON.stringify(details.recent_transactions, null, 2)}
            </pre>
          </React.Fragment>
        ) : (
          <Typography color="textSecondary">No additional data available.</Typography>
        )}
      </DialogContent>
    </Dialog>
  );
}
