function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// Update range displays
document.getElementById('minYear').addEventListener('input', updateYearRange);
document.getElementById('maxYear').addEventListener('input', updateYearRange);
document.getElementById('minPrice').addEventListener('input', updatePriceRange);
document.getElementById('maxPrice').addEventListener('input', updatePriceRange);
document.getElementById('minOdometer').addEventListener('input', updateMileageRange);
document.getElementById('maxOdometer').addEventListener('input', updateMileageRange);

function updateYearRange() {
    const min = document.getElementById('minYear').value;
    const max = document.getElementById('maxYear').value;
    document.getElementById('yearRange').textContent = `${min} - ${max}`;
}

function updatePriceRange() {
    const min = parseInt(document.getElementById('minPrice').value);
    const max = parseInt(document.getElementById('maxPrice').value);
    document.getElementById('priceRange').textContent = `$${min.toLocaleString()} - $${max.toLocaleString()}`;
}

function updateMileageRange() {
    const min = parseInt(document.getElementById('minOdometer').value);
    const max = parseInt(document.getElementById('maxOdometer').value);
    document.getElementById('mileageRange').textContent = `${min.toLocaleString()} - ${max.toLocaleString()}`;
}

document.getElementById('searchForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const manufacturers = Array.from(document.getElementById('manufacturer').selectedOptions).map(o => o.value);
    const types = Array.from(document.getElementById('type').selectedOptions).map(o => o.value);
    
    const filters = {
        manufacturers: manufacturers.length ? manufacturers : null,
        types: types.length ? types : null,
        min_year: document.getElementById('minYear').value || null,
        max_year: document.getElementById('maxYear').value || null,
        min_price: document.getElementById('minPrice').value || null,
        max_price: document.getElementById('maxPrice').value || null,
        min_odometer: document.getElementById('minOdometer').value || null,
        max_odometer: document.getElementById('maxOdometer').value || null,
        fuel: document.getElementById('fuel').value || null,
        transmission: document.getElementById('transmission').value || null,
        condition: document.getElementById('condition').value || null,
        color: document.getElementById('color').value || null,
        keywords: document.getElementById('keywords').value || null,
        sort_by: document.getElementById('sortBy').value
    };
    
    try {
        const startTime = performance.now();
        
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(filters)
        });
        
        const results = await response.json();
        const elapsed = Math.round(performance.now() - startTime);
        displayResults(results, elapsed);
    } catch (error) {
        document.getElementById('results').innerHTML = '<div class="empty-state">Error loading results</div>';
    }
});

function displayResults(results, elapsed) {
    const container = document.getElementById('results');
    const header = document.getElementById('resultsHeader');
    const count = document.getElementById('resultsCount');
    
    if (!results || results.length === 0) {
        header.style.display = 'none';
        container.replaceChildren(Object.assign(document.createElement('div'), {className: 'empty-state', textContent: 'No cars found matching your criteria'}));
        return;
    }
    
    header.style.display = 'block';
    count.textContent = `${results.length} car${results.length !== 1 ? 's' : ''} found in ${elapsed}ms`;
    
    // nosemgrep: insecure-innerhtml, insecure-document-method
    container.innerHTML = results.map(car => {
        const title = escapeHtml([car.year, car.manufacturer, car.model].filter(Boolean).join(' '));
        const price = car.price ? `$${escapeHtml(car.price.toLocaleString())}` : 'Price not listed';
        
        // Map type to image
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
            : '/static/images/img_sedan.jpeg';  // Default to sedan
        
        const badges = [];
        if (car.condition) {
            const conditionClass = car.condition === 'excellent' || car.condition === 'like new' ? 'condition-excellent' : 
                                   car.condition === 'good' ? 'condition-good' : '';
            badges.push(`<span class="badge ${escapeHtml(conditionClass)}">${escapeHtml(car.condition).toUpperCase()}</span>`);
        }
        if (car.fuel === 'electric' || car.fuel === 'hybrid') {
            badges.push(`<span class="badge">${escapeHtml(car.fuel).toUpperCase()}</span>`);
        }
        
        const details = [];
        if (car.odometer) details.push(`<div class="detail"><strong>Mileage:</strong> ${escapeHtml(car.odometer.toLocaleString())} miles</div>`);
        if (car.transmission) details.push(`<div class="detail"><strong>Transmission:</strong> ${escapeHtml(car.transmission)}</div>`);
        if (car.fuel) details.push(`<div class="detail"><strong>Fuel:</strong> ${escapeHtml(car.fuel)}</div>`);
        if (car.type) details.push(`<div class="detail"><strong>Body:</strong> ${escapeHtml(car.type)}</div>`);
        if (car.drive) details.push(`<div class="detail"><strong>Drive:</strong> ${escapeHtml(car.drive)}</div>`);
        if (car.cylinders) details.push(`<div class="detail"><strong>Engine:</strong> ${escapeHtml(car.cylinders)}</div>`);
        if (car.paint_color) details.push(`<div class="detail"><strong>Color:</strong> ${escapeHtml(car.paint_color)}</div>`);
        if (car.state) details.push(`<div class="detail"><strong>Location:</strong> ${escapeHtml(car.state).toUpperCase()}</div>`);
        
        const description = car.description ? 
            `<div class="description">${escapeHtml(car.description.substring(0, 500))}${car.description.length > 500 ? '...' : ''}</div>` : '';
        
        const altText = escapeHtml(car.type || 'sedan');
        const imageHtml = imageSrc 
            ? `<img src="${escapeHtml(imageSrc)}" alt="${altText}" style="width: 100%; height: 100%; object-fit: cover;">` 
            : 'No Image Available';
        
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
}

// Auto-search on page load with no filters
window.addEventListener('load', () => {
    // Initialize range displays
    updateYearRange();
    updatePriceRange();
    updateMileageRange();
    
    // Trigger search
    document.getElementById('searchForm').dispatchEvent(new Event('submit'));
});
