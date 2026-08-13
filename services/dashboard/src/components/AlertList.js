import React from 'react';
import { List, ListItem, ListItemText, Divider } from '@mui/material';

/**
 * AlertList displays a scrollable list of alerts.
 * Props:
 *   - alerts: array of alert objects
 *   - onSelect: function(alert) called when a list item is clicked
 */
export default function AlertList({ alerts, onSelect }) {
  return (
    <List dense>
      {alerts.map((a, i) => (
        <React.Fragment key={i}>
          <ListItem button alignItems="flex-start" onClick={() => onSelect && onSelect(a)}>
            <ListItemText
              primary={`${a.account_id} – ${a.type}`}
              secondary={`Score: ${a.drift_score?.toFixed(3)} | ${new Date(a.timestamp).toLocaleString()}`}
            />
          </ListItem>
          {i < alerts.length - 1 && <Divider component="li" />}
        </React.Fragment>
      ))}
      {alerts.length === 0 && (
        <ListItem>
          <ListItemText primary="No alerts yet." />
        </ListItem>
      )}
    </List>
  );
}
