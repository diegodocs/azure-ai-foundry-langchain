<script setup>
import { marked } from 'marked'

const props = defineProps({
  msg: { type: Object, required: true },
})

const agentLabels = {
  bing:   '🌐 Agente Web (Bing)',
  search: '📦 Catálogo (AI Search)',
  ticket: '🎫 Chamados (MCP)',
}

function renderBubble(msg) {
  const text = msg.content + (msg.streaming ? '<span class="cursor"></span>' : '')
  if (msg.role === 'agent') {
    try { return marked.parse(text) } catch { return text }
  }
  // Usuário: escapa HTML, preserva quebras de linha
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}
</script>

<template>
  <div :class="['row', msg.role]">
    <!-- Label do agente -->
    <div v-if="msg.role === 'agent' && msg.agent" :class="['agent-label', msg.agent]">
      <span class="dot"></span>
      {{ agentLabels[msg.agent] || msg.agent }}
    </div>

    <!-- Chips de ferramentas usadas -->
    <div v-if="msg.toolCalls?.length">
      <div
        v-for="tc in msg.toolCalls"
        :key="tc.tool + tc.query"
        class="tool-chip"
      >
        <span v-if="msg.streaming" class="spinner"></span>
        <span v-else>🔍</span>
        <span>{{ tc.tool }}: <em>{{ tc.query }}</em></span>
      </div>
    </div>

    <!-- Conteúdo da mensagem (markdown para agente, texto para usuário) -->
    <div class="bubble" v-html="renderBubble(msg)"></div>
  </div>
</template>
