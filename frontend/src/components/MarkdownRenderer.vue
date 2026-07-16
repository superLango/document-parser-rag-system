<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        // fall through
      }
    }
    return `<pre class="hljs"><code>${hljs.highlightAuto(code).value}</code></pre>`
  },
})

const html = computed(() => {
  if (!props.content) return ''
  return md.render(props.content)
})
</script>

<template>
  <div class="markdown-body" v-html="html"></div>
</template>

<style scoped lang="scss">
.markdown-body {
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--text-primary);

  :deep(p) {
    margin: 0 0 8px;
    &:last-child { margin-bottom: 0; }
  }

  :deep(h1), :deep(h2), :deep(h3), :deep(h4) {
    margin: 16px 0 8px;
    font-weight: 600;
    line-height: 1.3;
  }
  :deep(h1) { font-size: 1.3em; }
  :deep(h2) { font-size: 1.2em; }
  :deep(h3) { font-size: 1.1em; }
  :deep(h4) { font-size: 1em; }

  :deep(ul), :deep(ol) {
    margin: 0 0 8px;
    padding-left: 24px;
  }
  :deep(li) { margin: 2px 0; }

  :deep(code) {
    background: var(--bg-base);
    color: var(--accent-primary);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 0.9em;
  }

  :deep(pre.hljs) {
    background: var(--bg-base);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    overflow-x: auto;
    margin: 8px 0;

    code {
      background: transparent;
      color: var(--text-primary);
      padding: 0;
      font-size: 0.9em;
      line-height: 1.5;
    }
  }

  :deep(blockquote) {
    border-left: 3px solid var(--accent-primary);
    padding-left: 12px;
    margin: 8px 0;
    color: var(--text-secondary);
  }

  :deep(a) {
    color: var(--accent-primary);
    text-decoration: none;
    &:hover { text-decoration: underline; }
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    th, td {
      border: 1px solid var(--border-light);
      padding: 6px 12px;
      text-align: left;
    }
    th {
      background: var(--bg-surface-hover);
      font-weight: 600;
    }
  }
}
</style>
