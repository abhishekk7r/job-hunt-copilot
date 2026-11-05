import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';

export default defineConfig({
  server: { host: '127.0.0.1', port: 4399 },
  integrations: [
    mermaid({ theme: 'default', autoTheme: true }),
    starlight({
      title: 'Job Search Engine',
      description: 'How the local job-search system works, end to end.',
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        { label: 'Start here', items: [{ label: 'Overview', slug: '' }] },
        {
          label: 'How it works',
          items: [
            { label: 'The Run cycle', slug: 'run-cycle' },
            { label: 'Autonomy and decisions', slug: 'autonomy-and-decisions' },
            { label: 'Live progress', slug: 'live-progress' },
          ],
        },
        {
          label: 'Operate',
          items: [
            { label: 'Daily use', slug: 'operations' },
            { label: 'Go-live checklist', slug: 'go-live' },
            { label: 'Known gaps', slug: 'gaps' },
          ],
        },
      ],
    }),
  ],
});
