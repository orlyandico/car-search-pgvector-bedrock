function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function displayError(message) {
    const container = document.getElementById('results');
    // nosemgrep: insecure-innerhtml, insecure-document-method
    container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function displayResults(results, elapsed) {
    const container = document.getElementById('results');
    
    if (!results || results.length === 0) {
        container.innerHTML = '<div class="empty-state">No cars found</div>';
        return;
    }
    
    const header = `<div class="results-header" style="display:block;"><span>${escapeHtml(results.length)} car${results.length !== 1 ? 's' : ''} found in ${escapeHtml(elapsed)}ms</span></div>`;
    
    const cards = results.map(car => {
        const title = escapeHtml([car.year, car.manufacturer, car.model].filter(Boolean).join(' '));
        const price = car.price ? `$${escapeHtml(car.price.toLocaleString())}` : 'Price not listed';
        const similarity = car.similarity ? `${escapeHtml((car.similarity * 100).toFixed(1))}%` : '';
        
        const imageMap = {
            'sedan': 'img_sedan.jpeg',
            'suv': 'img_suv.jpeg',
            'truck': 'img_truck.jpeg',
            'coupe': 'img_coupe.jpeg',
            'hatchback': 'img_hatchback.jpeg',
            'wagon': 'img_wagon.jpeg',
            'van': 'img_van.jpeg',
            'convertible': 'img_convertible.jpeg'
        };
        const typeKey = car.type ? car.type.toLowerCase() : '';
        const imageSrc = imageMap[typeKey] 
            ? `/static/images/${imageMap[typeKey]}` 
            : '/static/images/img_sedan.jpeg';
        
        const badges = [];
        if (similarity) {
            badges.push(`<span class="badge">Match: ${escapeHtml(similarity)}</span>`);
        }
        if (car.condition) {
            const conditionClass = car.condition === 'excellent' || car.condition === 'like new' ? 'condition-excellent' : 
                                   car.condition === 'good' ? 'condition-good' : '';
            badges.push(`<span class="badge ${escapeHtml(conditionClass)}">${escapeHtml(car.condition).toUpperCase()}</span>`);
        }
        
        const details = [];
        if (car.odometer) details.push(`<div class="detail"><strong>Mileage:</strong> ${escapeHtml(car.odometer.toLocaleString())} miles</div>`);
        if (car.transmission) details.push(`<div class="detail"><strong>Transmission:</strong> ${escapeHtml(car.transmission)}</div>`);
        if (car.fuel) details.push(`<div class="detail"><strong>Fuel:</strong> ${escapeHtml(car.fuel)}</div>`);
        if (car.type) details.push(`<div class="detail"><strong>Body:</strong> ${escapeHtml(car.type)}</div>`);
        if (car.drive) details.push(`<div class="detail"><strong>Drive:</strong> ${escapeHtml(car.drive)}</div>`);
        if (car.paint_color) details.push(`<div class="detail"><strong>Color:</strong> ${escapeHtml(car.paint_color)}</div>`);
        if (car.state) details.push(`<div class="detail"><strong>Location:</strong> ${escapeHtml(car.state).toUpperCase()}</div>`);
        
        const description = car.description ? 
            `<div class="description">${escapeHtml(car.description.substring(0, 500))}${car.description.length > 500 ? '...' : ''}</div>` : '';
        
        const altText = escapeHtml(car.type || 'sedan');
        const imageHtml = `<img src="${escapeHtml(imageSrc)}" alt="${altText}" style="width: 100%; height: 100%; object-fit: cover;">`;
        
        return `
            <div class="result-card">
                <div class="result-image">${imageHtml}</div>
                <div class="result-content">
                    <h3>${title}</h3>
                    ${badges.join('')}
                    <div class="price">${price}</div>
                    <div class="details">${details.join('')}</div>
                    ${description}
                </div>
            </div>
        `;
    }).join('');
    
    // nosemgrep: insecure-innerhtml, insecure-document-method
    container.innerHTML = header + cards;
}
