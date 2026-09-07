# Priorformler – ÅkerPuls V1

För fält i, år t och gröda c:

`z_i,t = [H_i,t, X_i]`

`pi_i,t(c) = exp(F_c(z_i,t)) / sum_k exp(F_k(z_i,t))`

Där F är den frysta multiclass-M4-modellen. Historiken använder endast år < t.

Entropi:

`E_i,t = -sum_c pi_i,t(c) log pi_i,t(c)`

Top-1:

`c*_i,t = argmax_c pi_i,t(c)`

Satellitfusion om satellitmodellen levererar likelihood:

`P(C=c | S,H,X) proportional to P(S | C=c) pi_i,t(c)`

Om satellitmodellen levererar posterior q_sat tränad under klassprior pi_train:

`P(C=c | S,H,X) proportional to [q_sat(c|S)/pi_train(c)] pi_i,t(c)`

Normalisera över c efter fusion.
