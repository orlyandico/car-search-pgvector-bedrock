document.getElementById('chatForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const query = document.getElementById('queryInput').value.trim();
    if (!query) return;
    
    try {
        const startTime = performance.now();
        const response = await fetch('/api/hybrid', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query})
        });
        
        const results = await response.json();
        const elapsed = Math.round(performance.now() - startTime);
        
        if (results.error) {
            displayError(results.error);
        } else {
            displayResults(results, elapsed);
        }
    } catch (error) {
        displayError('Something went wrong');
    }
});

