import { ref, reactive } from 'vue'

// Proxy do Vite redireciona /api → http://localhost:8088/api
const API_BASE = '/api'

export function useChat() {
  const messages = ref([])
  const loading = ref(false)
  const sessionId = ref(null)
  let msgIdCounter = 0

  async function sendMessage(text) {
    if (!text || loading.value) return

    // Mensagem do usuário
    messages.value.push({ id: ++msgIdCounter, role: 'user', content: text })

    // Placeholder do agente (atualizado em streaming)
    const agentMsg = reactive({
      id: ++msgIdCounter,
      role: 'agent',
      agent: '',
      content: '',
      toolCalls: [],
      streaming: true,
    })
    messages.value.push(agentMsg)
    loading.value = true

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId.value }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // linha incompleta

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let evt
          try { evt = JSON.parse(line.slice(6)) } catch { continue }

          if (evt.type === 'session_id')      sessionId.value = evt.session_id
          else if (evt.type === 'agent')      agentMsg.agent = evt.agent
          else if (evt.type === 'tool_call')  agentMsg.toolCalls.push({ tool: evt.tool, query: evt.query })
          else if (evt.type === 'token')      agentMsg.content += evt.content
          else if (evt.type === 'done')       agentMsg.streaming = false
          else if (evt.type === 'error') {
            agentMsg.content = `⚠️ Erro: ${evt.message}`
            agentMsg.streaming = false
          }
        }
      }
    } catch (err) {
      agentMsg.content = `⚠️ Falha na conexão: ${err.message}`
      agentMsg.streaming = false
    } finally {
      loading.value = false
      agentMsg.streaming = false
    }
  }

  return { messages, loading, sendMessage }
}
