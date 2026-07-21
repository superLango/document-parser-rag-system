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

<style scoped>
.markdown-body {
  font-size: 0.875rem;
  line-height: 1.7;
  color: var(--foreground);
}

.markdown-body :deep(p) {
  margin: 0 0 8px;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--foreground);
}
.markdown-body :deep(h1) { font-size: 1.3em; }
.markdown-body :deep(h2) { font-size: 1.2em; }
.markdown-body :deep(h3) { font-size: 1.1em; }
.markdown-body :deep(h4) { font-size: 1em; }

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 8px;
  padding-left: 24px;
}
.markdown-body :deep(li) {
  margin: 2px 0;
}

.markdown-body :deep(code) {
  background: var(--muted);
  color: var(--primary);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.markdown-body :deep(pre.hljs) {
  background: var(--muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body :deep(pre.hljs code) {
  background: transparent;
  color: var(--foreground);
  padding: 0;
  font-size: 0.9em;
  line-height: 1.5;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--primary);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--muted-foreground);
}

.markdown-body :deep(a) {
  color: var(--primary);
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body :deep(table th),
.markdown-body :deep(table td) {
  border: 1px solid var(--border);
  padding: 6px 12px;
  text-align: left;
}
.markdown-body :deep(table th) {
  background: var(--muted);
  font-weight: 600;
}
</style>
