import React, { useEffect, useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogContentText, CircularProgress } from '@mui/material';

/**
 * HeatmapDetail shows a modal with detailed account info when a heatmap cell is clicked.
 * Props:
 *   - open: boolean
 *   - onClose: () => void
 *   - accountId: string – the account tied to the selected cell
 */
export default function HeatmapDetail({ open, onClose, accountId }) {
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!open || !accountId) return;
    setLoading(true);
    fetch(`${process.env.REACT_APP_API_URL}/api/v1/accounts/${accountId}/drift`)
      .then(r => r.json())
      .then(json => setDetail(json))
      .catch(e => console.error('Heatmap detail fetch error', e))
      .finally(() => setLoading(false));
  }, [open, accountId]);

  if (!accountId) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Account Risk Details – {accountId}</DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <CircularProgress />
        ) : detail ? (
          <React.Fragment>
            <DialogContentText>
              <strong>Current Drift Score:</strong> {detail.drift_score?.toFixed(3)}
            </DialogContentText>
            <pre style={{ background: '#f5f5f5', padding: '8px', overflowX: 'auto' }}>
{JSON.stringify(detail, null, 2)}
            </pre>
          </React.Fragment>
        ) : (
          <DialogContentText>No details available.</DialogContentText>
        )}
      </DialogContent>
    </Dialog>
  );
}
