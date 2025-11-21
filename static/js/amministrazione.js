function creaGrafico(id) {
    const ctx = document.getElementById(id).getContext('2d');
    return new Chart(ctx, {
        type: 'pie',
        data: {
            labels: ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio"],
            datasets: [{
                data: [12, 19, 7, 15, 22],
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });
}

creaGrafico('grafico1');
creaGrafico('grafico2');
creaGrafico('grafico3');
creaGrafico('grafico4');