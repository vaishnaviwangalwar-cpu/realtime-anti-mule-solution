import React, { useEffect, useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogContentText, CircularProgress, Divider, Typography } from '@mui/material';

/**
 * NetworkDetail displays detailed information for a selected cluster/node.
 * Props:
 *   - open: boolean
 *   - onClose: () => void
 *   - clusterId: string – the identifier of the selected cluster (or node)
 */
export default function NetworkDetail({ open, onClose, clusterId }) {
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!open || !clusterId) return;
    setLoading(true);
    fetch(`${process.env.REACT_APP_API_URL}/api/v1/graph/cluster/${clusterId}`)
      .then(r => r.json())
      .then(json => setDetail(json))
      .catch(e => console.error('Network detail fetch error', e))
      .finally(() => setLoading(false));
  }, [open, clusterId]);

  if (!clusterId) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Cluster Details – {clusterId}</DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <CircularProgress />
        ) : detail ? (
          <React.Fragment>
            <DialogContentText>
              <strong>Member Accounts:</strong> {detail.accounts?.join(', ') || 'N/A'}
            </DialogContentText>
            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>Recent Transactions (sample)</Typography>
            <pre style={{ background: '#f5f5f5', padding: '8px', overflowX: 'auto' }}>
{JSON.stringify(detail.recent_transactions, null, 2)}
            </pre>
          </React.Fragment>
        ) : (
          <DialogContentText>No details available.</DialogContentText>
        )}
      </DialogContent>
    </Dialog>
  );
}
