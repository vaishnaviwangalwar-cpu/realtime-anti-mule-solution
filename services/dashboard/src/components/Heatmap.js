import React, { useRef, useEffect } from 'react';
import * as d3 from 'd3';
import { Paper } from '@mui/material';

/**
 * Heatmap renders a grid of risk scores. When a cell is clicked, it calls onCellClick(accountId).
 * Props:
 *   - data: [{ account_id: string, score: number }]
 *   - onCellClick?: (accountId: string) => void
 */
export default function Heatmap({ data, onCellClick }) {
  const ref = useRef();

  useEffect(() => {
    const svg = d3.select(ref.current);
    svg.selectAll('*').remove();
    if (!data?.length) return;

    const width = 600,
      height = 350;
    const cols = Math.ceil(Math.sqrt(data.length));
    const size = Math.min(width / cols, height / cols);

    const color = d3.scaleSequential(d3.interpolateReds).domain([0, d3.max(data, d => d.score) || 1]);

    const g = svg
      .append('g')
      .attr('transform', `translate(${(width - cols * size) / 2},${(height - cols * size) / 2})`);

    const tooltip = d3
      .select('body')
      .append('div')
      .attr('class', 'tooltip')
      .style('position', 'absolute')
      .style('pointer-events', 'none')
      .style('opacity', 0)
      .style('background', '#fff')
      .style('border', '1px solid #ccc')
      .style('padding', '4px')
      .style('font-size', '12px');

    g.selectAll('rect')
      .data(data)
      .enter()
      .append('rect')
      .attr('x', (_, i) => (i % cols) * size)
      .attr('y', (_, i) => Math.floor(i / cols) * size)
      .attr('width', size - 2)
      .attr('height', size - 2)
      .attr('fill', d => color(d.score))
      .on('mouseover', (event, d) => {
        tooltip
          .style('opacity', 1)
          .html(`Account: ${d.account_id}<br/>Score: ${d.score.toFixed(3)}`)
          .style('left', `${event.pageX + 8}px`)
          .style('top', `${event.pageY - 28}px`);
      })
      .on('mouseout', () => tooltip.style('opacity', 0))
      .on('click', (_, d) => {
        if (onCellClick) onCellClick(d.account_id);
      });

    return () => tooltip.remove();
  }, [data, onCellClick]);

  return <svg ref={ref} width={620} height={380} />;
}
