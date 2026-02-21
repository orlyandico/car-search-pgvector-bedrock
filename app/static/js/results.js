function displayError(message) {
    const container = document.getElementById('results');
    container.innerHTML = `<div class="empty-state">${message}</div>`;
}

function displayResults(results, elapsed) {
    const container = document.getElementById('results');
    
    if (!results || results.length === 0) {
        container.innerHTML = '<div class="empty-state">No cars found</div>';
        return;
    }
    
    const header = `<div class="results-header" style="display:block;"><span>${results.length} car${results.length !== 1 ? 's' : ''} found in ${elapsed}ms</span></div>`;
    
    const cards = results.map(car => {
        const title = [car.year, car.manufacturer, car.model].filter(Boolean).join(' ');
        const price = car.price ? `$${car.price.toLocaleString()}` : 'Price not listed';
        const similarity = car.similarity ? `${(car.similarity * 100).toFixed(1)}%` : '';
        
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
        const imageSrc = car.type && imageMap[car.type.toLowerCase()] 
            ? `/static/images/${imageMap[car.type.toLowerCase()]}` 
            : '/static/images/img_sedan.jpeg';
        
        const badges = [];
        if (similarity) {
            badges.push(`<span class="badge">Match: ${similarity}</span>`);
        }
        if (car.condition) {
            const conditionClass = car.condition === 'excellent' || car.condition === 'like new' ? 'condition-excellent' : 
                                   car.condition === 'good' ? 'condition-good' : '';
            badges.push(`<span class="badge ${conditionClass}">${car.condition.toUpperCase()}</span>`);
        }
        
        const details = [];
        if (car.odometer) details.push(`<div class="detail"><strong>Mileage:</strong> ${car.odometer.toLocaleString()} miles</div>`);
        if (car.transmission) details.push(`<div class="detail"><strong>Transmission:</strong> ${car.transmission}</div>`);
        if (car.fuel) details.push(`<div class="detail"><strong>Fuel:</strong> ${car.fuel}</div>`);
        if (car.type) details.push(`<div class="detail"><strong>Body:</strong> ${car.type}</div>`);
        if (car.drive) details.push(`<div class="detail"><strong>Drive:</strong> ${car.drive}</div>`);
        if (car.paint_color) details.push(`<div class="detail"><strong>Color:</strong> ${car.paint_color}</div>`);
        if (car.state) details.push(`<div class="detail"><strong>Location:</strong> ${car.state.toUpperCase()}</div>`);
        
        const description = car.description ? 
            `<div class="description">${car.description.substring(0, 500)}${car.description.length > 500 ? '...' : ''}</div>` : '';
        
        const imageHtml = `<img src="${imageSrc}" alt="${car.type || 'sedan'}" style="width: 100%; height: 100%; object-fit: cover;">`;
        
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
    
    container.innerHTML = header + cards;
}
