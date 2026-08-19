import React, { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import { Box } from '@mui/material';

/**
 * NetworkGraph renders an interactive mule account network visualization using Cytoscape.
 * Props:
 *   - data: { nodes: [{ data: { id, label, type, ... } }], edges: [{ data: { id, source, target, label, ... } }] } or { clusters: [...] }
 *   - onNodeClick: (nodeId) => void
 *   - onClusterClick: (clusterId) => void
 */
export default function NetworkGraph({ data, onNodeClick, onClusterClick }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Transform cluster update data or standard node/edge data
    let elements = [];
    if (data?.elements) {
      elements = data.elements;
    } else if (data?.nodes || data?.edges) {
      elements = [
        ...(data.nodes || []).map(n => (n.data ? n : { data: n })),
        ...(data.edges || []).map(e => (e.data ? e : { data: e }))
      ];
    } else if (data?.clusters) {
      // Visual graph from clusters summary
      const nodes = [];
      const edges = [];
      data.clusters.forEach((c, idx) => {
        const clusterNodeId = c.cluster_id || `cluster_${idx}`;
        nodes.push({
          data: {
            id: clusterNodeId,
            label: `${clusterNodeId} (${c.size || 1} accs)`,
            type: 'cluster',
            size: 30 + Math.min(30, (c.size || 1) * 3)
          }
        });
        if (c.members && Array.isArray(c.members)) {
          c.members.slice(0, 8).forEach(accId => {
            nodes.push({
              data: {
                id: accId,
                label: accId,
                type: 'account',
                size: 20
              }
            });
            edges.push({
              data: {
                id: `${clusterNodeId}-${accId}`,
                source: clusterNodeId,
                target: accId
              }
            });
          });
        }
      });
      elements = [...nodes, ...edges];
    }

    if (elements.length === 0) {
      elements = [
        { data: { id: 'ACC-000102', label: 'ACC-000102 (Mule)', type: 'mule' } },
        { data: { id: 'ACC-000455', label: 'ACC-000455 (Hub)', type: 'hub' } },
        { data: { id: 'ACC-000912', label: 'ACC-000912 (Recv)', type: 'receiver' } },
        { data: { id: 'e1', source: 'ACC-000102', target: 'ACC-000455', label: '$4,500' } },
        { data: { id: 'e2', source: 'ACC-000455', target: 'ACC-000912', label: '$4,200' } }
      ];
    }

    // Initialize Cytoscape
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#1976d2',
            'label': 'data(label)',
            'color': '#fff',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '11px',
            'font-weight': 'bold',
            'text-outline-color': '#0d47a1',
            'text-outline-width': 2,
            'width': 40,
            'height': 40
          }
        },
        {
          selector: 'node[type = "mule"], node[type = "cluster"]',
          style: {
            'background-color': '#d32f2f',
            'text-outline-color': '#b71c1c'
          }
        },
        {
          selector: 'node[type = "hub"]',
          style: {
            'background-color': '#f57c00',
            'text-outline-color': '#e65100'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#90caf9',
            'target-arrow-color': '#1976d2',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '9px',
            'color': '#333'
          }
        }
      ],
      layout: {
        name: 'cose',
        animate: true,
        randomize: false,
        componentSpacing: 80,
        nodeOverlap: 20,
        idealEdgeLength: 60,
        edgeElasticity: 100
      }
    });

    cyRef.current.on('tap', 'node', (evt) => {
      const node = evt.target;
      const id = node.id();
      const type = node.data('type');
      if (type === 'cluster' && onClusterClick) {
        onClusterClick(id);
      } else if (onNodeClick) {
        onNodeClick(id);
      }
    });

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
      }
    };
  }, [data, onNodeClick, onClusterClick]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        minHeight: 520,
        backgroundColor: '#fafafa',
        borderRadius: 1
      }}
    />
  );
}
