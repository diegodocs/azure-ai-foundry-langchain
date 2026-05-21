<script setup>
import { ref, nextTick } from 'vue'
import AppHeader    from './components/AppHeader.vue'
import MessageList  from './components/MessageList.vue'
import ChatInput    from './components/ChatInput.vue'
import { useChat }  from './composables/useChat.js'

const { messages, loading, sendMessage } = useChat()

const input       = ref('')
const chatInputRef = ref(null)

function handleSend(text) {
  sendMessage(text)
}

function handleSuggestion(suggestion) {
  // Remove emoji inicial + espaços e preenche o campo
  input.value = suggestion.replace(/^[\p{Emoji}\s]+/u, '').trim()
  nextTick(() => chatInputRef.value?.focus())
}
</script>

<template>
  <AppHeader />
  <MessageList
    :messages="messages"
    @suggestion="handleSuggestion"
  />
  <ChatInput
    ref="chatInputRef"
    v-model="input"
    :loading="loading"
    @send="handleSend"
  />
</template>
