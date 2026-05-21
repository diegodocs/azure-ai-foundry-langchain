<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  loading:    { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'send'])

const textarea = ref(null)

// Expõe focus() para o componente pai
defineExpose({
  focus() { textarea.value?.focus() },
})

function handleSend() {
  const text = props.modelValue.trim()
  if (!text || props.loading) return
  emit('send', text)
  emit('update:modelValue', '')
  if (textarea.value) textarea.value.style.height = 'auto'
}

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}
</script>

<template>
  <div class="input-area">
    <div class="input-row">
      <textarea
        :value="modelValue"
        :disabled="loading"
        placeholder="Digite sua mensagem… (Enter para enviar)"
        rows="1"
        ref="textarea"
        @input="e => { emit('update:modelValue', e.target.value); autoResize(e) }"
        @keydown.enter.exact.prevent="handleSend"
      ></textarea>
      <button
        class="send-btn"
        :disabled="loading || !modelValue.trim()"
        @click="handleSend"
        title="Enviar"
      >
        <span v-if="loading">⏳</span>
        <span v-else>➤</span>
      </button>
    </div>
    <p class="hint">
      Enter para enviar · Shift+Enter para nova linha ·
      <strong>Bing</strong> · <strong>AI Search</strong> · <strong>MCP Tickets</strong>
    </p>
  </div>
</template>
