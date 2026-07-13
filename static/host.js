(() => {
  const layout = document.querySelector('.console-layout');
  if (!layout) return;
  const hostId = layout.dataset.hostId;
  const form = document.querySelector('#execute-form');
  const input = document.querySelector('#command-input');
  const count = document.querySelector('#command-count');
  const button = document.querySelector('#execute-button');
  const output = document.querySelector('#terminal-output');
  const outputLabel = document.querySelector('#output-label');
  const exitCode = document.querySelector('#exit-code');

  function updateCount() { count.textContent = `${input.value.length} / 4096`; }
  input.addEventListener('input', updateCount);
  input.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  async function execute(command) {
    if (!command.trim()) return;
    input.value = command;
    updateCount();
    button.disabled = true;
    button.textContent = '正在发送…';
    outputLabel.textContent = '正在连接主机';
    exitCode.textContent = '';
    output.textContent = `$ ${command}\n\n正在等待 SSH 响应…`;
    try {
      const result = await window.ui.api(`/api/hosts/${hostId}/execute`, {
        method: 'POST', body: JSON.stringify({ command })
      });
      const sections = [`$ ${command}`];
      if (result.stdout) sections.push(result.stdout);
      if (result.stderr) sections.push(`[STDERR]\n${result.stderr}`);
      if (result.error) sections.push(`[连接失败]\n${result.error}`);
      if (result.truncated) sections.push('[输出超过 1 MiB，已截断]');
      output.textContent = sections.join('\n\n');
      outputLabel.textContent = result.error ? '执行失败' : '执行完成';
      exitCode.textContent = result.exit_code === null ? 'NO EXIT CODE' : `EXIT ${result.exit_code}`;
      document.querySelector('#generated-url').value = result.generated_url;
      document.querySelector('#link-result').classList.remove('hidden');
    } catch (exception) {
      outputLabel.textContent = '请求失败';
      output.textContent = `[请求失败]\n${exception.message}`;
      window.ui.showToast(exception.message, true);
    } finally {
      button.disabled = false;
      button.textContent = '发送并生成 URL';
    }
  }

  form.addEventListener('submit', event => { event.preventDefault(); execute(input.value); });
  document.querySelectorAll('.preset-command').forEach(item => {
    item.addEventListener('click', () => execute(item.dataset.command));
  });

  document.querySelector('#wake-button')?.addEventListener('click', async event => {
    const wakeButton = event.currentTarget;
    wakeButton.disabled = true;
    try {
      const result = await window.ui.api(`/api/hosts/${hostId}/wake`, { method: 'POST', body: '{}' });
      document.querySelector('#wake-url').value = result.generated_url;
      window.ui.showToast(result.message);
    } catch (exception) {
      window.ui.showToast(exception.message, true);
    } finally {
      wakeButton.disabled = false;
    }
  });

  document.querySelector('#rotate-key')?.addEventListener('click', async () => {
    if (!window.confirm('轮换后，这台主机之前生成的所有执行和唤醒链接都会失效。继续吗？')) return;
    try {
      const result = await window.ui.api(`/api/hosts/${hostId}/rotate-link-key`, { method: 'POST', body: '{}' });
      document.querySelector('#wake-url').value = result.wake_url;
      document.querySelector('#link-result').classList.add('hidden');
      window.ui.showToast(result.message);
    } catch (exception) {
      window.ui.showToast(exception.message, true);
    }
  });
})();
