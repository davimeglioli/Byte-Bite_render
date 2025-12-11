//bisogna disabilitare i tasti del summaty anche quando si raggiunge la quantita massima

document.addEventListener("DOMContentLoaded", () => {

    // Gestione tabs categorie
    const tabs = document.querySelectorAll(".tab");
    const productSections = document.querySelectorAll(".products");

    function mostraCategoria(nomeCategoria) {
        productSections.forEach(sezione => sezione.classList.remove("active"));
        const sezioneDaMostrare = document.querySelector(`.products[data-categoria="${nomeCategoria}"]`);
        if (sezioneDaMostrare) sezioneDaMostrare.classList.add("active");

        tabs.forEach(tab => {
            tab.classList.toggle("active", tab.dataset.categoria === nomeCategoria);
        });
    }

    if (tabs.length > 0) mostraCategoria(tabs[0].dataset.categoria);

    tabs.forEach(tab => {
        tab.addEventListener("click", () => mostraCategoria(tab.dataset.categoria));
    });


    // Gestione carrello e riepilogo
    const carrello = [];
    const riepilogo = document.querySelector(".order-summary");
    const totaleElemento = document.querySelector(".total h2:last-child");
    const campoProdotti = document.getElementById("prodotti-json");

    function aggiornaRiepilogo() {
        riepilogo.innerHTML = "";
        let totale = 0;

        carrello.forEach(item => {
            const subtotale = item.prezzo * item.quantita;
            totale += subtotale;

            const div = document.createElement("div");
            div.classList.add("item");
            div.innerHTML = `
                <h5>${item.nome}</h5>
                <div class="item-controls">
                    <button class="btn-decrease" data-id="${item.id}">-</button>
                    <p>${item.quantita}</p>
                    <button class="btn-increase" data-id="${item.id}">+</button>
                    <button class="btn-remove" data-id="${item.id}">×</button>
                    <p>€${subtotale.toFixed(2)}</p>
                </div>
            `;
            riepilogo.appendChild(div);
        });

        totaleElemento.textContent = `€${totale.toFixed(2)}`;
        campoProdotti.value = JSON.stringify(carrello);
        aggiornaQuantitaProdotti();
    }

    function aggiungiProdotto(id, nome, prezzo, maxDisponibile) {
        const esistente = carrello.find(p => p.id === id);
        if (esistente) {
            if (esistente.quantita < maxDisponibile) esistente.quantita++;
        } else {
            carrello.push({ id, nome, prezzo, quantita: 1 });
        }
        aggiornaRiepilogo();
    }

    function rimuoviProdotto(id) {
        const index = carrello.findIndex(p => p.id === id);
        if (index !== -1) {
            carrello[index].quantita--;
            if (carrello[index].quantita <= 0) carrello.splice(index, 1);
        }
        aggiornaRiepilogo();
    }

    document.addEventListener("click", (e) => {
        // Gestione pulsanti nelle card
        if (e.target.classList.contains("btn-plus")) {
            const prodottoDiv = e.target.closest(".product");
            const id = parseInt(prodottoDiv.dataset.id);
            const nome = prodottoDiv.querySelector("h4").textContent;
            const prezzo = parseFloat(prodottoDiv.dataset.prezzo);
            const maxDisponibile = parseInt(prodottoDiv.dataset.quantita);
            aggiungiProdotto(id, nome, prezzo, maxDisponibile);
        }

        if (e.target.classList.contains("btn-minus")) {
            const prodottoDiv = e.target.closest(".product");
            const id = parseInt(prodottoDiv.dataset.id);
            rimuoviProdotto(id);
        }

        // Gestione pulsanti nel riepilogo
        if (e.target.classList.contains("btn-increase")) {
            const id = parseInt(e.target.dataset.id);
            const item = carrello.find(p => p.id === id);
            const prodottoDiv = document.querySelector(`.product[data-id="${id}"]`);
            const maxDisponibile = prodottoDiv ? parseInt(prodottoDiv.dataset.quantita) : Infinity;
            if (item && item.quantita < maxDisponibile) {
                item.quantita++;
                aggiornaRiepilogo();
            }
        }

        if (e.target.classList.contains("btn-decrease")) {
            const id = parseInt(e.target.dataset.id);
            rimuoviProdotto(id);
        }

        if (e.target.classList.contains("btn-remove")) {
            const id = parseInt(e.target.dataset.id);
            const index = carrello.findIndex(p => p.id === id);
            if (index !== -1) carrello.splice(index, 1);
            aggiornaRiepilogo();
        }
    });

    function aggiornaQuantitaProdotti() {
        document.querySelectorAll(".product").forEach(prodottoDiv => {
            const id = parseInt(prodottoDiv.dataset.id);
            const prodottoCarrello = carrello.find(p => p.id === id);
            const quantityElement = prodottoDiv.querySelector(".quantity p");
            const btnPlus = prodottoDiv.querySelector(".btn-plus");
            const btnMinus = prodottoDiv.querySelector(".btn-minus");
            const maxDisponibile = parseInt(prodottoDiv.dataset.quantita);

            if (prodottoCarrello) {
                quantityElement.textContent = prodottoCarrello.quantita;
                prodottoDiv.classList.add("product-selected");
                btnPlus.disabled = prodottoCarrello.quantita >= maxDisponibile;
                btnMinus.disabled = prodottoCarrello.quantita <= 0;
                const riepilogoPlus  = document.querySelector(`.btn-increase[data-id="${id}"]`);
                const riepilogoMinus = document.querySelector(`.btn-decrease[data-id="${id}"]`);

                if (riepilogoPlus)  riepilogoPlus.disabled  = prodottoCarrello.quantita >= maxDisponibile;
                if (riepilogoMinus) riepilogoMinus.disabled = prodottoCarrello.quantita <= 1;
            } else {
                quantityElement.textContent = 0;
                prodottoDiv.classList.remove("product-selected");
                btnPlus.disabled = false;
                btnMinus.disabled = true;
            }

            [btnPlus, btnMinus].forEach(btn => {
                btn.style.opacity = btn.disabled ? "0.5" : "1";
                btn.style.cursor = btn.disabled ? "not-allowed" : "pointer";
            });
        });
    }

    // Esegui inizializzazione al caricamento
    aggiornaQuantitaProdotti();


    // Gestione ordini e asporto
    const checkboxAsporto = document.getElementById("isTakeaway");
    const tavoloWrapper = document.getElementById("tavolo-wrapper");
    const personeWrapper = document.getElementById("persone-wrapper");
    const campoTavolo = document.getElementById("customer-table");
    const campoPersone = document.getElementById("customer-people");

    function aggiornaVisibilitaCampi() {
        const asporto = checkboxAsporto.checked;
        tavoloWrapper.style.display = asporto ? "none" : "block";
        personeWrapper.style.display = asporto ? "none" : "block";

        if (asporto) {
            campoTavolo.removeAttribute("required");
            campoPersone.removeAttribute("required");
            campoTavolo.value = "";
            campoPersone.value = "";
        } else {
            campoTavolo.setAttribute("required", "required");
            campoPersone.setAttribute("required", "required");
        }
    }

    checkboxAsporto.addEventListener("change", aggiornaVisibilitaCampi);
    aggiornaVisibilitaCampi();
});

let lastTouchEnd = 0;
document.removeEventListener('touchend', function(){});
document.removeEventListener('touchmove', function(){});
